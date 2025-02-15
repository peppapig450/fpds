"""
Base classes for FPDS XML Processing

This module provides an efficient implementation for processing FPDS (Federal Procurement 
Data System) XML data using modern Python features and async processing.

author: derek663@gmail.com
last_updated: 02/14/2025
"""
from typing_extensions import TypeAlias, override

from collections.abc import Iterator
from dataclasses import dataclass
from enum import StrEnum, auto
from functools import cached_property
import re
from typing import Final, Annotated, Any
from io import BytesIO

from lxml import etree

from fpds.core import FPDS_ENTRY
from fpds.core.mixins import fpdsMixin, fpdsXMLMixin, XMLElement

# Type aliases for clarity
XMLContent: TypeAlias = bytes | XMLElement

# Using Annotated for better type hints
ValidXMLString = Annotated[str, "XML string with potential namespace"]

# Constants with Final for immutability and clarity
NAMESPACE_PATTERN: Final[str] = r"\{(.*)\}"
LAST_PAGE_PATTERN: Final[str] = r"start=(.*?)$"
DEFAULT_RESPONSE_SIZE: Final[int] = 10

class EntryType(StrEnum):
    """Enumeration for FPDS entry types"""
    AWARD = auto()
    IDV = auto()
    UNKNOWN = auto()
    
@dataclass(frozen=True, slots=True)
class EntryMetadata:
    """Immutable container for entry metadata using slots for memory efficiency"""
    contract_type: EntryType
    title: str
    modified_date: str
    link: str


class fpdsXML(fpdsXMLMixin, fpdsMixin):
    """
    XML document parser for FPDS data
    """

    def __init__(self, content: XMLContent) -> None:
        """
        Initialize the XML parser with either bytes or an ElementTree.
        
        Args:
            content: Raw XML content as bytes or parsed ElementTree
        
        Raises:
            TypeError: If content type is invalid
        """
        match content:
            case bytes():
                self.content = content
                self.tree = etree.XML(content, parser=None)
            case element if isinstance(content, XMLElement):
                self.tree: XMLElement = element # type: ignore
            case _:
                module_names = ",".join(
                    [f"`{mod}`" for mod in self.xml_child_classes_with_modules]
                )
                raise TypeError(
                    f"Content must be bytes or one of: {module_names}"
                )

    def __str__(self) -> str:  # pragma: no cover
        """Provide a descriptive string representation of the XML document"""
        root = self.tree
        query = root.find(".//{*}title", namespaces=None)
        page = root.find(".//{*}link[@rel='alternate']", namespaces=None)
        return (
            f"<fpdsXML query={query.text if query is not None else ''} "
            f"page={page.get('href', '') if page is not None else ''}>"
        )
        
    @cached_property
    def response_size(self) -> int:
        """Cache the response size since it's constant per instance"""
        return DEFAULT_RESPONSE_SIZE
    
    @cached_property
    def lower_limit(self) -> int:
        """
        Calculate and cache the lower limit for pagination.
        """
        last_link = self.tree.find(".//{*}link[@rel='last']", namespaces=None)
        match last_link:
            case None:
                return len(list(self.iter_entries()))
            case link:
                href = link.get("href", "")
                if match := re.search(LAST_PAGE_PATTERN, href):
                    return int(match.group(1))
                return len(list(self.iter_entries()))

    def parse_items(self) -> Iterator[etree._Element]:
        """Returns iteration of `Element` as a generator."""
        yield from self.tree.iter(tag=None)

    def convert_to_lxml_tree(self) -> etree._Element:
        """Returns an `ElementTree` object from a `bytes` response."""
        return etree.XML(self.content, parser=None)

    def pagination_links(self, params: str) -> list[str]:
        """Builds pagination links for a single API response based on the
        total record count value.
        """
        resp_size = self.response_size
        offset = 0 if self.lower_limit < 10 else resp_size
        page_range = list(range(0, self.lower_limit + offset, resp_size))
        return [f"{self.url_base}&q={params}&start={num}" for num in page_range]

    def iter_entries(self) -> Iterator[etree._Element]:
        """
        Streams through the XML content using iterparse.
        Each <entry> element is yielded and then cleared to free memory.
        """
        with BytesIO(self.content) as xml_buffer:
            for _, elem in etree.iterparse(
                xml_buffer,
                events=("end",),
                tag="{*}entry",
                recover=True
            ):
                    yield elem
                    # Clear the element from memory.
                    elem.clear()
                    # Also eliminate now-empty references from the root
                    while elem.getprevious() is not None:
                        del elem.getparent()[0]

    def jsonify(self) -> list[FPDS_ENTRY]:
        """
        Convert XML entries to JSON-compatible dictionary format
        """
        return [Entry(content=elem)() for elem in self.iter_entries()]


class fpdsElement(fpdsXML):
    """
    Representation of a single FPDS XML element. This utility class helps us
    retrieve the name of XML tags without the namespace.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        # Ensure self.element is an lxml.etree._Element.
        self.element: XMLElement = self.tree
        del self.tree

    @override
    def __str__(self) -> str:  # pragma: no cover
        return f"<fpdsElement {self.clean_tag}>"

    @cached_property
    def clean_tag(self) -> str:
        """Tag name without the namespace. A tag like the following:
        `ns1:productOrServiceInformation` would simply return
        `productOrServiceInformation`.
        """
        return re.sub(self.NAMESPACE_REGEX_PATTERN, "", self.element.tag)


class Entry(fpdsElement):
    """New as of v1.2.0

    Representation of a single FPDS award item. In terms of XML, it is the
    outermost container for award data. Each entry contains four children tags --
    `title`, `link`, `modified`, and `content`. The `content` tag will contain
    the bulk of data to be extracted, but tags like `title` and `modified`
    also contain useful info.

    Example:
    --------

     <entry>
        <title>
            <![CDATA[PURCHASE ORDER 1B3G02670 (PA09) awarded to MC ALLEN CITY OF, was modified for the amount of $8,392.9]]>
        </title>
        <link rel="alternate" type="text/html" href="https://www.fpds.gov/ezsearch/search.do?s=FPDS&amp;indexName=awardfull&amp;templateName=1.5.3&amp;q=1B3G02670+4740+"></link>
        <modified>2013-12-18 17:03:03</modified>
        <content xmlns:ns1="https://www.fpds.gov/FPDS" type="application/xml">
            <ns1:award xmlns:ns1="https://www.fpds.gov/FPDS" version="1.4">
                <ns1:awardID>
                    <ns1:awardContractID>
                        <ns1:agencyID name="PUBLIC BUILDINGS SERVICE">4740</ns1:agencyID>
    </entry>
    """
    
    @cached_property
    def metadata(self) -> EntryMetadata:
        """
        Cache entry metadata for repeated access.
        Returns an immutable EntryMetadata object.
        """
        content_elem = self.element.find(".//{*}content", namespaces=None)
        contract_type = EntryType.UNKNOWN
        if content_elem is not None and len(content_elem):
            award_tag = re.sub(
                self.NAMESPACE_REGEX_PATTERN, 
                "", 
                content_elem[0].tag
            ).upper()
            try:
                contract_type = EntryType[award_tag]
            except KeyError:
                contract_type = EntryType.UNKNOWN
                
        title_elem = self.element.find(".//{*}title", namespaces=None)
        modified_elem = self.element.find(".//{*}modified", namespaces=None)
        link_elem = self.element.find(
            ".//{*}link[@rel='alternate']", 
            namespaces=None
        )

        return EntryMetadata(
            contract_type=contract_type,
            title=title_elem.text if title_elem is not None else "",
            modified_date=modified_elem.text if modified_elem is not None else "",
            link=link_elem.get("href", "") if link_elem is not None else ""
        )


    def get_entry_data(self) -> dict[str, Any]:
        """
        Extracts award data from an entry as a nested dictionary.
        The structure preserves the original XML hierarchy.
        An additional 'contract_type' field is injected.
        """
        base_data = self.to_nested_dict(self.element)
        root_tag = next(iter(base_data))
           
        return {
            root_tag: base_data[root_tag] | {
                "contract_type": self.metadata.contract_type.value
            }
        }
        
    def __call__(self) -> FPDS_ENTRY:
        """Make the entry callable for convenient data extraction"""
        return self.get_entry_data()