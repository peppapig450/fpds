"""
Base classes for FPDS XML elements.

author: derek663@gmail.com
last_updated: 08/21/2024
"""

import asyncio
import multiprocessing
from asyncio import Semaphore
from concurrent.futures import ProcessPoolExecutor
from typing import List, Optional, Union
from urllib import parse
from urllib.request import urlopen
from xml.etree.ElementTree import ElementTree, fromstring

from aiohttp import ClientSession

from fpds.core import FPDS_ENTRY
from fpds.core.mixins import fpdsMixin
from fpds.core.xml import fpdsXML
from fpds.errors import fpdsMaxPageLengthExceededError, fpdsMissingKeywordParameterError
from fpds.utilities import validate_kwarg

def process_pages(pages: list[fpdsXML]) -> list[FPDS_ENTRY]:
    """
    Helper function for parallel processing.
    
    Given a list of fpdsXML pages, converts each page to a list of FPDS_ENTRYs
    using the fpdsRequest._jsonify static method and returns a single flattened list.
    """
    result: list[FPDS_ENTRY] = []
    for page in pages:
        result.extend(fpdsRequest._jsonify(page))
    return result

class fpdsRequest(fpdsMixin):
    """Makes a GET request to the FPDS ATOM feed. Takes an unlimited number of
    arguments. All query parameters should be submitted as strings. If new
    arguments are added to the feed, add the argument to the
    `fpds/core/constants.json` file. During class instantiation, this class
    will validate argument names and values and raise a `ValueError` if any
    error exists.

    Example:
        request = fpdsRequest(
            LAST_MOD_DATE="[2022/01/01, 2022/05/01]",
            AGENCY_CODE="7504"
        )

    Attributes
    ----------
    cli_run: `bool`
        Defaults to `False`.
        Flag indicating if this class is being isntantiated by a CLI run.
    thread_count: `int`
        Defaults to 10.
        The number of threads to send per search.
    page: `Optional[int]`
        Defaults to `None`.
        The results page to retrieve.

    Raises
    ------
    fpdsDuplicateParameterConfiguration:
        Raised if duplicate configurations for a single parameter exist.

    fpdsInvalidParameter:
        Raised if an invalid parameter is provided.

    fpdsMaxPageLengthExceededError:
        Raised if user requests a page of results that doesn't exist.

    fpdsMismatchedParameterRegexError:
        Raised if parameter value does not match expected regex pattern.

    fpdsMissingKeywordParameterError:
        Raised if no keyword argument(s) are provided.
    """

    def __init__(
        self,
        cli_run: bool = False,
        thread_count: int = 10,
        page: Optional[int] = None,
        **kwargs,
    ):
        self.cli_run = cli_run
        self.thread_count = thread_count
        self.page = page
        self.links: list[str] = []

        if kwargs:
            self.kwargs = kwargs
        else:
            raise fpdsMissingKeywordParameterError

        # Perform the initial request (synchronously) to obtain pagination links.
        # We pass raw bytes so that fpdsXML handles the conversion.
        initial_content = self.initial_request()
        tree = fpdsXML(content=initial_content)
        links = tree.pagination_links(params=self.search_params)
        self.links = links

        if self.page:
            idx = self.page_index()
            if idx is not None and self.links:
                if self.page > self.page_count:
                    raise fpdsMaxPageLengthExceededError(page_count=self.page_count)
                self.links = [links[idx]]

        # do not run class validations since CLI command has its own
        if not self.cli_run:
            for kwarg, value in self.kwargs.items():
                self.kwargs[kwarg] = validate_kwarg(kwarg=kwarg, string=value)

    def __str__(self) -> str:  # pragma: no cover
        """String representation of `fpdsRequest`."""
        kwargs_str = " ".join([f"{key}={value}" for key, value in self.kwargs.items()])
        return f"<fpdsRequest {kwargs_str}>"

    def __url__(self) -> str:  # pragma: no cover
        """Custom magic method for request URL."""
        return f"{self.url_base}&q={self.search_params}"

    @property
    def search_params(self) -> str:
        """Search parameters inputted by user."""
        _params = [f"{key}:{value}" for key, value in self.kwargs.items()]
        return " ".join(_params)

    @property
    def page_count(self) -> int:
        """Total number of FPDS pages contained in request."""
        return len(self.links)

    @staticmethod
    def convert_to_lxml_tree(content: Union[str, bytes]) -> ElementTree:
        """Returns lxml tree element from a `bytes` response."""
        tree = ElementTree(fromstring(content))
        return tree

    def initial_request(self) -> bytes:
        """
        Sends the initial (synchronous) request to the FPDS ATOM feed
        and returns the raw response bytes.
        """
        encoded_params = parse.urlencode({"q": self.search_params})
        url = f"{self.url_base}&{encoded_params}"
        with urlopen(url) as response:
            return response.read()

    async def convert(self, session: ClientSession, link: str) -> fpdsXML:
        """
        Retrieves and converts content from a FPDS ATOM feed link into an fpdsXML object.
        """
        async with session.get(link) as response:
            content = await response.read()
            return fpdsXML(content=content)

    async def _fetch_with_semaphore(
        self, session: ClientSession, link: str, semaphore: Semaphore
    ) -> fpdsXML:
        async with semaphore:
            return await self.convert(session, link)

    async def fetch(self) -> List[fpdsXML]:
        """
        Asynchronously retrieves FPDS XML pages using a shared semaphore to limit
        concurrency.
        """
        if not self.links:
            return []
        semaphore = Semaphore(self.thread_count)
        async with ClientSession() as session:
            tasks = [
                self._fetch_with_semaphore(session, link, semaphore)
                for link in self.links
            ]
            return await asyncio.gather(*tasks)

    def page_index(self) -> Optional[int]:
        """
        Converts the requested page (if any) to a zero-based index.
        """
        if self.page:
            return 0 if self.page == 1 else self.page - 1
        return None

    @staticmethod
    def _jsonify(page: fpdsXML) -> List[FPDS_ENTRY]:
        """
        Converts a single fpdsXML page into a list of FPDS_ENTRY dictionaries.
        """
        return page.jsonify()

    async def data(self) -> List[FPDS_ENTRY]:
        """
        Retrieves FPDS data by fetching all pages and converting each to a
        nested JSON-like dictionary. The conversion is offloaded to a process pool.
        """
        pages = await self.fetch()
        num_processes = multiprocessing.cpu_count()
        loop = asyncio.get_running_loop()
        with ProcessPoolExecutor(max_workers=num_processes) as pool:
            # Offload the mapping to the process pool (blocking call wrapped in run_in_executor)
            results: List[FPDS_ENTRY] = await loop.run_in_executor(
                pool, process_pages, pages
            )
        # Flatten the list of lists into a single list of entries.
        return results