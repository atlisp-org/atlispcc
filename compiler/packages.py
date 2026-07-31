from typing import Dict, List, Optional, Set

PACKAGE_SEP = '|'

class Package:
    def __init__(self, name: str):
        self.name = name
        self.exports: Set[str] = set()
        self.use: List[str] = []

class PackageTable:
    def __init__(self):
        self.packages: Dict[str, Package] = {}
        self.current_package: Optional[str] = None

    def add_package(self, name: str, use: List[str], export: List[str]):
        pkg = Package(name)
        pkg.use = list(use)
        pkg.exports = set(export)
        self.packages[name] = pkg

    def set_current(self, name: str):
        self.current_package = name

    def current(self) -> Optional[Package]:
        if self.current_package and self.current_package in self.packages:
            return self.packages[self.current_package]
        return None

    def munge(self, pkg: str, name: str) -> str:
        return f'{pkg}{PACKAGE_SEP}{name}'

    def resolve(self, name: str) -> str:
        if PACKAGE_SEP in name:
            return name
        idx = name.find(':')
        if idx > 0:
            pkg_part = name[:idx]
            sym_part = name[idx + 1:]
            return self.munge(pkg_part, sym_part)
        return name

    def demunge(self, name: str) -> str:
        idx = name.find(PACKAGE_SEP)
        if idx > 0:
            pkg_part = name[:idx]
            sym_part = name[idx + 1:]
            return f'{pkg_part}:{sym_part}'
        return name
