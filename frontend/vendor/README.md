# Vendored libraries

Served as-is from `/static/vendor/` and imported as native ES modules by
`frontend/app/chat/markdown.js`. There is no build step: to upgrade, download
the new files from jsDelivr, replace them here, update the table below, and
re-run the browser suite (`backend/tests/test_frontend_browser.py`).

| File | Package | Version | Source | License | SHA-384 (SRI form) |
|---|---|---|---|---|---|
| `markdown-it.esm.js` | markdown-it | 15.0.3 | https://cdn.jsdelivr.net/npm/markdown-it@15.0.3/dist/browser/markdown-it.esm.min.min.mjs | MIT | `sha384-GuK+KNk4xdRoijRpS6dOg775D7qx5r9F+snnaiAydawmpv6mBZiGIbUR2gZNTb1p` |
| `purify.es.js` | dompurify | 3.4.17 | https://cdn.jsdelivr.net/npm/dompurify@3.4.17/dist/purify.es.min.mjs | Apache-2.0 OR MPL-2.0 | `sha384-wt12O1FKtKIrH+m8GwJ5wd9xBTOJWaH0iwhJpjXiQjLbN52ox0n59yLOrhO+Zo4T` |

Both are jsDelivr's Terser-minified renditions of the published ES module
builds (`dist/browser/markdown-it.esm.min.mjs`, `dist/purify.es.mjs`); the
unminified originals hash to
`sha384-7yjzCPkG764NlEaGnmJUs6zIxtNw3AyINNUvcqtZzLH1ehuETg3q+sfiN30NQmaX` and
`sha384-BL58nOFQzaquDpMkbuU2wPuzK53BYxRB4AUTPJekFOA6woO0vIOBxW6Qe4kwM1HH`.
The only local edit is removing the trailing `//# sourceMappingURL=/sm/...`
comment, which would point at our own origin and 404 in devtools. Files are
renamed from `.mjs` to `.js` so every static host serves them with a
JavaScript MIME type (required for module scripts). Gzipped: about 41 KB and
12 KB. The SHA-384 column is the hash of the file as shipped; verify with:

```sh
openssl dgst -sha384 -binary markdown-it.esm.js | openssl base64 -A
```

Icons added for the chat UI (`frontend/assets/icons/`: arrow-up-bold,
arrow-down, arrow-clockwise, stop-fill, pencil-simple, phone, chat-text,
globe-simple, lifebuoy, wifi-slash, download-simple) come from
`@phosphor-icons/core@2.1.1` (MIT), the same set as the existing icons.
