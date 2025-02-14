"""
fpds mixin classes

author: derek663@gmail.com
last_updated: 06/05/2024
"""

import re
from xml.etree.ElementTree import Element, ElementTree
from typing import Any


class fpdsMixin:
    @property
    def url_base(self) -> str:
        """Base URL for all ATOM feed requests"""
        return "https://www.fpds.gov/ezsearch/FEEDS/ATOM?FEEDNAME=PUBLIC"


class fpdsXMLMixin:
    @property
    def xml_child_classes(self):
        """Classes from the `xml` API that inherit from `ElementTree` module"""
        return (ElementTree, Element)

    @property
    def xml_child_classes_with_modules(self):
        """Fully qualified module name for classes in `xml_child_classes`"""
        classes = (ElementTree, Element)
        return [f"{cls.__module__}.{cls.__qualname__}" for cls in classes]

    @property
    def NAMESPACE_REGEX_PATTERN(self) -> str:
        """Regex pattern to match any of the namespaces found in the XML."""
        namespaces = "|".join(self.namespace_dict.values())  # type: ignore
        return r"\{(" + namespaces + r")\}"

    def to_nested_dict(self, element: Element | None = None) -> dict:
        """
        Recursively converts an XML element into a nested dictionary that preserves the hierarchy.

        Each element is converted to a dictionary with:
          - its tag name as the key (namespaces are stripped),
          - a sub-dictionary containing:
              - attributes (stored under the key "@attributes"),
              - text content (stored under the key "#text"), and
              - nested child elements.

        If no element is provided, the method attempts to use `self.element` (if set)
        or the root of `self.tree`.

        Returns
        -------
        dict
            A nested dictionary representation of the XML.
        """
        if element is None:
            if hasattr(self, "element"):
                element = self.element
            elif hasattr(self, "tree"):
                element = (
                    self.tree.getroot()
                    if isinstance(self.tree, ElementTree)
                    else self.tree
                )
            else:
                raise ValueError("No XML element available for conversion.")

        pattern = re.compile(self.NAMESPACE_REGEX_PATTERN)

        def recursive_dict(elem: Element) -> dict:
            tag = pattern.sub("", elem.tag)
            node: dict[str, Any] = {}
            if elem.attrib:
                node["@attributes"] = elem.attrib
            text = (elem.text or "").strip()
            if text:
                node["#text"] = text
            children = list(elem)
            if children:
                child_nodes: dict[str, Any] = {}
                for child in children:
                    child_dict = recursive_dict(child)
                    # child_dict is a dict with one key: the child tag (without namespace)
                    for child_tag, child_value in child_dict.items():
                        if child_tag in child_nodes:
                            if isinstance(child_nodes[child_tag], list):
                                child_nodes[child_tag].append(child_value)
                            else:
                                child_nodes[child_tag] = [
                                    child_nodes[child_tag],
                                    child_value,
                                ]
                        else:
                            child_nodes[child_tag] = child_value
                node.update(child_nodes)
            return {tag: node}

        return recursive_dict(element)
