"""Backend test package.

A package, not a namespace portion: `tests.conftest` is imported by name, and a
namespace directory loses that lookup to any regular `tests` package elsewhere on
sys.path. Before this marker existed the host resolved it to a different project
and every one of those imports failed.
"""
