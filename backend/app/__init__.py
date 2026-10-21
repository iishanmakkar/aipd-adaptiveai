"""AdaptiveAI backend application package.

Present so that `import app` resolves to this directory. Without it the tree is
a namespace portion, and Python's path finder prefers any regular package it
finds further along sys.path - which is how a host-side test run silently
imported a different project's `app` (measured: D:/geospatial/geomeasure).
"""
