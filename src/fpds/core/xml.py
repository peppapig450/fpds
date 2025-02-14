"""
XML classes for parsing FPDS content.

author: derek663@gmail.com
last_updated: 07/13/2024
"""

import re
from typing import Dict, Iterator, List, Optional, Union, Any
from xml.etree.ElementTree import Element, ElementTree, fromstring

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

    def __init__(self, content: Union[bytes, ElementTree]) -> None:
        if isinstance(content, bytes):
            self.content = content
            self.tree = self.convert_to_lxml_tree()
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
        if isinstance(self.tree, ElementTree):
            root = self.tree.getroot()
            query = root.find(".//ns0:title", self.namespace_dict)
            assert isinstance(query, Element)

            page = root.find(".ns0:link[@rel='alternate']", self.namespace_dict)
            assert isinstance(page, Element)

            return f"<fpdsXML query=`{query.text}` page=`{page.attrib['href']}`>"

    def parse_items(self) -> Iterator[Element]:
        """Returns iteration of `Element` as a generator."""
        yield from self.tree.iter()

    def convert_to_lxml_tree(self) -> ElementTree:
        """Returns an `ElementTree` object from a `bytes` response."""
        tree = ElementTree(fromstring(self.content))
        return tree

    @staticmethod
    def _get_full_namespace(element: Element) -> str:
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
        """Lower limit of record count (i.e. if 40, it means there is a total of
        40-49 records).
        """
        last_link = self.tree.find(".//ns0:link[@rel='last']", self.namespace_dict)
        if isinstance(last_link, Element):
            # length of last_link should always be 1
            match = re.search(LAST_PAGE_REGEX, last_link.attrib["href"])
            assert match is not None
            record_count = int(match.group(1))
        else:
            record_count = len(self.get_atom_feed_entries())
        return record_count

    def pagination_links(self, params: str) -> List[str]:
        """Builds pagination links for a single API response based on the
        total record count value.
        """
        resp_size = self.response_size
        offset = 0 if self.lower_limit < 10 else resp_size
        page_range = list(range(0, self.lower_limit + offset, resp_size))
        return [f"{self.url_base}&q={params}&start={num}" for num in page_range]

    def get_atom_feed_entries(self) -> List[Element]:
        """Returns tree entries that contain FPDS record data."""
        return self.tree.findall(".//ns0:entry", self.namespace_dict)

    def jsonify(self) -> List[FPDS_ENTRY]:
        """Returns all paginated entries from an FPDS request."""
        entries = self.get_atom_feed_entries()
        return [Entry(content=entry)() for entry in entries]


class fpdsElement(fpdsXML):
    """Representation of a single FPDS XML element. This utility class helps us
    retrieve the name of XML tags without the namespace.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        # Ensure self.element is an Element (not an ElementTree)
        if isinstance(self.tree, ElementTree):
            self.element = self.tree.getroot()
        else:
            self.element = self.tree
        delattr(self, "tree")

    def __str__(self) -> str:  # pragma: no cover
        return f"<fpdsElement {self.tag}>"

    def parse_items(self) -> Iterator[Element]:
        """Returns iteration of `Element` as a generator."""
        yield from self.element.iter()

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
        content = self.element.find(".//ns0:content", self.namespace_dict)
        if content is not None and list(content):
            award = list(content)[0]
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

    def content_tag_hierarchy(
        self,
        element: Optional[Element] = None,
        parent: Optional[str] = None,
        hierarchy: Optional[Dict[str, str]] = None,
    ) -> Dict[str, str]:
        """Added on v1.2.0

        For each FPDS request made, the `entry` tag represents an individual
        award -- `AWARD` or `IDV`. The `content` tag contains a nested structure
        of tags with all relevant award metadata. In v1.0.0, this parser assumed
        each tag name to be unique, which caused duplicate tag names to be
        overwritten. In the example below, we can see two groupings of tags --
        `awardContractID` and `referencedIDVID` -- containing duplicate tag
        names `agencyID`, `PIID`, and `modNumber`. Because the referenced IDV tag
        succeeds the original award contract tag, only the referenced IDV data
        tags would exist in the final JSON structure. To ensure that we capture
        all data and correctly distinguish between an award PIID and referenced
        IDV PIID, this function will recursively parse through each entry's
        structure and generate a concatenated string of tag names.

        <content xmlns:ns1="https://www.fpds.gov/FPDS" type="application/xml">
            <ns1:awardID>
                <ns1:awardContractID>
                    <ns1:agencyID name="ENVIRONMENTAL PROTECTION AGENCY">6800</ns1:agencyID>
                    <ns1:PIID>0002</ns1:PIID>
                    <ns1:modNumber>P00018</ns1:modNumber>
                    <ns1:transactionNumber>0</ns1:transactionNumber>
                </ns1:awardContractID>
                <ns1:referencedIDVID>
                    <ns1:agencyID name="ENVIRONMENTAL PROTECTION AGENCY">6800</ns1:agencyID>
                    <ns1:PIID>EPS31703</ns1:PIID>
                    <ns1:modNumber>0</ns1:modNumber>
                </ns1:referencedIDVID>
            </ns1:awardID>
        </content>

        Parameters
        ----------
        element: `Optional[Element]`
            Per docs, to get children simply iterate over element
            https://lxml.de/api/lxml.etree._Element-class.html#getchildren.
        parent: `Optional[str]`
            Name of `elements` XML parent.
        hierarchy: `Dict[str, str]`
            The hierarchy dictionary structure to be passed through each
            recursive function call.
        """
        if hierarchy is None:
            hierarchy = {}

        if element is None:
            element = self.element  # type: ignore

        _parent = Parent(content=element)
        # continue parsing XML hierarchy because children exist and we want
        # to get every possible bit of data
        if _parent.children():
            for child in _parent.children():
                _child = Parent(content=child, parent_name=parent)
                parent_tag_name = _child.parent_child_hierarchy_name()
                hierarchy[parent_tag_name] = child

                self.content_tag_hierarchy(
                    element=child,
                    parent=parent_tag_name,
                    hierarchy=hierarchy,
                )
        return hierarchy


class Parent(fpdsElement):
    """Identifies an xml tag as a parent. In this package, a parent tag
    is considered to have children elements.
    """

    def __init__(self, parent_name=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.parent_name = parent_name

    def children(self):
        """Returns children if they exist."""
        if list(self.element):
            return list(self.element)

    def parent_child_hierarchy_name(self, delim="__"):
        if self.parent_name:
            name = self.parent_name + delim + self.clean_tag
        else:
            name = self.clean_tag
        return name
