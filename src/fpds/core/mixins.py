"""
Enhanced FPDS mixin classes for XML processing with Python 3.12 features.

This module provides mixins for handling FPDS (Federal Procurement Data System) XML data
with improved type safety, performance optimizations, and clearer structure.

author: derek663@gmail.com
last_updated: 02/14/2024
"""

from typing_extensions import TypeAlias

from functools import cached_property
import re
from typing import Any, Final
from dataclasses import dataclass
from lxml import etree
from lxml.etree import _Element

# Type aliases for improved clarity
XMLElement: TypeAlias = _Element
XMLDict: TypeAlias = dict[str, Any]


@dataclass(frozen=True)
class XMLNodeData:
    """Container for XML node data"""

    attributes: dict[str, str]
    text: str
    children: dict[str, Any]


class fpdsMixin:
    """Base mixin providing FPDS-specific functionality."""

    URL_BASE: Final[str] = "https://www.fpds.gov/ezsearch/FEEDS/ATOM?FEEDNAME=PUBLIC"

    @property
    def url_base(self) -> str:
        """
        Get base URL for all ATOM feed requests.

        Returns:
            Base URL string for FPDS ATOM feed
        """

        return self.URL_BASE


class fpdsXMLMixin:
    """
    Mixin for XML processing.

    This mixin provides utilities for converting XML elements to dictionaries
    while preserving hierarchy and handling namespaces efficiently.
    """

    @cached_property
    def xml_child_classes(self) -> tuple[type[XMLElement]]:
        """
        Get tuple of XML element classes that inherit from ElementTree.

        Returns:
            Tuple containing XML element types
        """
        return (etree._Element,)

    @cached_property
    def xml_child_classes_with_modules(self) -> list[str]:
        """
        Get fully qualified module names for XML element classes.

        Returns:
            List of fully qualified class names
        """
        return [
            f"{cls.__module__}.{cls.__qualname__}" for cls in self.xml_child_classes
        ]

    @property
    def NAMESPACE_REGEX_PATTERN(self) -> str:
        """
        Generate regex pattern for matching XML namespaces.

        This property uses cached_property for performance optimization
        since the pattern compilation is expensive and the result doesn't change.

        Returns:
            Compiled regex pattern string

        Note:
            Assumes self.namespace_dict is defined in the implementing class
        """
        if not hasattr(self, "namespace_dict"):
            raise AttributeError(
                "namespace_dict must be defined in the implementing class"
            )

        namespaces = "|".join(self.namespace_dict.values())  # type: ignore
        return r"\{(" + namespaces + r")\}"

    def to_nested_dict(self, element: XMLElement | None = None) -> XMLDict:
        """
        Convert an XML element to a nested dictionary preserving hierarchy.

        This method provides an efficient way to transform XML data into a more
        easily manipulatable Python dictionary structure. It handles:
        - Attribute preservation
        - Text content
        - Nested elements
        - Namespace stripping
        - Multiple occurrences of the same tag

        Args:
            element: XML element to convert. If None, tries to use self.element
                    or self.tree.

        Returns:
            Nested dictionary representing the XML structure

        Raises:
            ValueError: If no XML element is available for conversion

        Example:
            >>> xml = '<root><child attr="value">text</child></root>'
            >>> mixin = fpdsXMLMixin()
            >>> result = mixin.to_nested_dict(etree.fromstring(xml))
            >>> print(result)
            {
                'root': {
                    'child': {
                        'attributes': {'attr': 'value'},
                        'text': 'text'
                    }
                }
            }
        """
        if element is None:
            element = self._get_default_element()

        namespace_pattern = re.compile(self.NAMESPACE_REGEX_PATTERN)

        def create_node_data(elem: XMLElement) -> XMLNodeData:
            """Create a container for node data."""
            return XMLNodeData(
                attributes=dict(elem.attrib) if elem.attrib else {},
                text=(elem.text or "").strip(),
                children={},
            )

        def process_child_nodes(
            node_data: XMLNodeData, children: list[XMLElement]
        ) -> None:
            """Process child nodes and handle multiple occurences of tags."""
            for child in children:
                child_dict = recursive_dict(child)
                for child_tag, child_value in child_dict.items():
                    if child_tag in node_data.children:
                        existing = node_data.children[child_tag]
                        if isinstance(existing, list):
                            existing.append(child_value)
                        else:
                            node_data.children[child_tag] = [existing, child_value]
                    else:
                        node_data.children[child_tag] = child_value

        def recursive_dict(elem: XMLElement) -> XMLDict:
            """
            Recursively convert XML element to dictionary.

            This inner function handles the actual recursive conversion process
            while maintaining clean code organization.
            """
            tag = namespace_pattern.sub("", elem.tag)
            node_data = create_node_data(elem)

            children = list(elem)  # type: ignore
            if children:
                process_child_nodes(node_data, children)

            # Build the final node dictionary
            node: XMLDict = {}
            if node_data.attributes:
                node["attributes"] = node_data.attributes
            if node_data.text:
                node["text"] = node_data.text
            node.update(node_data.children)

            return {tag: node}

        return recursive_dict(element)

    def _get_default_element(self) -> XMLElement:
        """
        Get the default XML element for processing.

        Returns:
            Default XML element to process

        Raises:
            ValueError: If no default element can be found
        """
        if hasattr(self, "element"):
            return self.element  # type: ignore
        elif hasattr(self, "tree"):
            tree = self.tree  # type: ignore
            return tree.getroot() if hasattr(tree, "getroot") else tree
        raise ValueError("No XML element available for conversion.")
