"""
XML classes for parsing FPDS content.

author: derek663@gmail.com
last_updated: 02/14/2025
"""

import re
from typing import Dict, Iterator, List, Union, Any
from io import BytesIO

from lxml import etree

from fpds.core import FPDS_ENTRY
from fpds.core.mixins import fpdsMixin, fpdsXMLMixin

NAMESPACE_REGEX = r"\{(.*)\}"
LAST_PAGE_REGEX = r"start=(.*?)$"


class fpdsXML(fpdsXMLMixin, fpdsMixin):
    """Parses FPDS request content received as `bytes` or `ElementTree`.
    This class represents an entire XML document.

    Attributes
    ----------
    content: `Union[bytes, ElementTree]`
        `bytes` content or an `ElementTree` type that can be parsed into
        valid XML.

    Raises
    ------
    TypeError:
        If `content` is not of type `bytes` or an instance of `ElementTree`.
    """

    def __init__(self, content: Union[bytes, etree._Element]) -> None:
        if isinstance(content, bytes):
            self.content = content
            self.tree = etree.XML(content, parser=None)
        elif isinstance(content, self.xml_child_classes):
            self.tree = content
        else:
            module_names = ",".join(
                [f"`{mod}`" for mod in self.xml_child_classes_with_modules]
            )
            raise TypeError(
                f"You must provide bytes content or an instance of the "
                f"following: {module_names}."
            )

    def __str__(self) -> str:  # pragma: no cover
        """The root represents the top of the XML tree from an instance of type
        `ElementTree`. Since `fpdsElement` inherits from this class, we overwrite
        this method in child classes since `getroot()` is not available for
        tags of type `Element`.
        """
        root = self.tree
        query = root.find(".//{*}title", namespaces=None)
        page = root.find(".//{*}link[@rel='alternate']", namespaces=None)
        query_text = query.text if query is not None else ""
        page_href = page.get("href") if page is not None else ""
        return f"<fpdsXML query={query_text} page={page_href}>"

    def parse_items(self) -> Iterator[etree._Element]:
        """Returns iteration of `Element` as a generator."""
        yield from self.tree.iter(tag=None)

    def convert_to_lxml_tree(self) -> etree._Element:
        """Returns an `ElementTree` object from a `bytes` response."""
        return etree.XML(self.content, parser=None)

    @staticmethod
    def _get_full_namespace(element: etree._Element) -> str:
        """For some odd reason, the `xml` API doesn't have a method to provide
        namespaces natively unless an XML file is saved locally. To avoid this,
        we just do some regex work.

        Parameters
        ----------
        element: `Element`
            An lxml Element type.
        """
        namespace = re.match(NAMESPACE_REGEX, element.tag)
        return namespace.group(1) if namespace else ""

    @property
    def response_size(self) -> int:
        """Max number of records in a single response."""
        return 10

    @property
    def namespace_dict(self) -> Dict[str, str]:
        """The better way of parsing tree elements with namespaces, per the docs.
        Note that `namespaces` is a list, which retains parsing order of the
        tree, which will be important in identifying Atom entries in `fpds`.

        https://docs.python.org/3/library/xml.etree.elementtree.html#parsing-xml-with-namespaces
        """
        namespaces = []
        for element in self.parse_items():
            ns = self._get_full_namespace(element)
            if ns and ns not in namespaces:
                namespaces.append(ns)

        return {f"ns{idx}": ns for idx, ns in enumerate(namespaces)}

    @property
    def lower_limit(self) -> int:
        last_link = self.tree.find(".//{*}link[@rel='last']", namespaces=None)
        if last_link is not None:
            match = re.search(LAST_PAGE_REGEX, last_link.get("href", ""))
            if match:
                record_count = int(match.group(1))
            else:
                record_count = len(list(self.iter_entries()))
        else:
            record_count = len(list(self.iter_entries()))
        return record_count

    def pagination_links(self, params: str) -> List[str]:
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
        with BytesIO(self.content) as f:
            # Use recover=True to handle any slight XML malformations.
            context = etree.iterparse(f, events=("end",), recover=True)
            for event, elem in context:
                if etree.QName(elem).localname == "entry":
                    yield elem
                    # Clear the element from memory.
                    elem.clear()
            del context

    def get_atom_feed_entries(self) -> List[etree._Element]:
        """Returns tree entries that contain FPDS record data."""
        return list(self.tree.findall(".//{*}entry", namespaces=None))

    def jsonify(self) -> List[FPDS_ENTRY]:
        """
        Converts each <entry> element to a FPDS_ENTRY dictionary.
        This uses streaming iterparse so that we don’t hold the entire
        document in memory.
        """
        entries = []
        for elem in self.iter_entries():
            entry = Entry(content=elem)()
            entries.append(entry)
        return entries


class fpdsElement(fpdsXML):
    """Representation of a single FPDS XML element. This utility class helps us
    retrieve the name of XML tags without the namespace.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        # Ensure self.element is an lxml.etree._Element.
        self.element = self.tree
        delattr(self, "tree")

    def __str__(self) -> str:  # pragma: no cover
        return f"<fpdsElement {self.tag}>"

    def parse_items(self) -> Iterator[etree._Element]:
        yield from self.element.iter(tag=None)

    @property
    def NAMESPACE_REGEX_PATTERN(self) -> str:
        """A single regex pattern string that allows us to remove all
        namespaces from tags, irrespective of namespace value.
        """
        namespaces = "|".join(self.namespace_dict.values())
        return r"\{(" + namespaces + r")\}"

    @property
    def tag(self):
        """Raw tag from `xml` library."""
        return self.element.tag

    @property
    def clean_tag(self) -> str:
        """Tag name without the namespace. A tag like the following:
        `ns1:productOrServiceInformation` would simply return
        `productOrServiceInformation`.
        """
        return re.sub(self.NAMESPACE_REGEX_PATTERN, "", self.tag)


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

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)

    def __str__(self) -> str:  # pragma: no cover
        return f"<Entry {self.clean_tag}>"

    def __call__(self) -> FPDS_ENTRY:  # pragma: no cover
        """Shortcut for the finalized data structure."""
        return self.get_entry_data()

    @property
    def contract_type(self) -> str:
        """Identifies the contract type for an individual award entry. Possible
        options include: `AWARD` or `IDV`.
        """
        content = self.element.find(".//{*}content", namespaces=None)
        if content is not None and len(content):
            award = content[0]
            award_type = re.sub(self.NAMESPACE_REGEX_PATTERN, "", award.tag)
            return award_type.upper()
        return ""

    def get_entry_data(self) -> Dict[str, Any]:
        """
        Extracts award data from an entry as a nested dictionary.
        The structure preserves the original XML hierarchy.
        An additional 'contract_type' field is injected.
        """
        # Convert the XML into a nested dictionary
        data = self.to_nested_dict(self.element)
        # data is a dict with a single key (typically 'entry'); add contract_type inside it.
        root_tag = next(iter(data))
        data[root_tag]["contract_type"] = self.contract_type
        return data
