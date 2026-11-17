# Bundled dependency sources

Setuptools 84.2.1 and Pillow 13.0.0 are unmodified official PyPI wheels.
The twitter-text-parser 3.0.0+flowsteward.1 wheel preserves the upstream parser,
emoji data and licenses, replacing its resource loader with Python 3.12
`importlib.resources`. Upstream 3.0.0 imports `pkg_resources`, which is absent
in setuptools 84. The patch changes no character weights or URL rules.

`dependency-sources.json` records the official source URL/hash, exact patch and
output hash. Reproduce offline after downloading that exact upstream wheel:

```
python scripts/rebuild_twitter_text.py /path/to/upstream-wheels /path/to/output
```

The transformation verifies source and patch hashes and regenerates wheel RECORD.
