"""
fpds mixin classes

author: derek663@gmail.com
last_updated: 06/05/2024
"""

import re
from functools import cached_property
from xml.etree.ElementTree import Element, ElementTree


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
        with_modules = [cls.__module__ + f".{cls.__qualname__}" for cls in classes]
        return with_modules

    @cached_property
    def compiled_namespace_regex(self) -> re.Pattern:
        """
        Returns a compiled regex that matches any of the namespaces
        in the namespace dictionary. This is cached so it only compiles once.
        """
        # Escape each namespace value for safety
        namespaces = "".join(re.escape(ns) for ns in self.namespace_dict.values()) # type: ignore
        pattern_str = r"\{(" + namespaces + r")\}"
        return re.compile(pattern_str)
    
    @property
    def NAMESPACE_REGEX_PATTERN(self) -> str:
        """
        Returns the regex pattern string. For actual matching operations,
        consider using the compiled regex (self.compiled_namespace_regex).
        """
        return self.compiled_namespace_regex.pattern
