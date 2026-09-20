# Third-Party Notices

DocSifter is distributed under the MIT License (see [LICENSE](LICENSE)). It also
redistributes the files below inside the package, so that the Web UI renders
without contacting a CDN. Each keeps its own license.

Regenerate these with `python3 tools/build_vendor_assets.py`.

## Tailwind CSS

- File: `src/docsifter/static/vendor/tailwind.min.css`
- Version: 2.2.19
- License: MIT
- Source: https://github.com/tailwindlabs/tailwindcss

Shipped as a generated subset: only the utility classes the DocSifter Web UI
references are kept. The upstream banner is preserved in the file. The bundle
embeds modern-normalize v1.1.0 (MIT,
https://github.com/sindresorhus/modern-normalize).

```
MIT License

Copyright (c) Tailwind Labs, Inc.

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## Font Awesome Free

- Files: `src/docsifter/static/vendor/fontawesome.min.css`,
  `src/docsifter/static/vendor/fa-solid-900.woff2`,
  `src/docsifter/static/vendor/fa-brands-400.woff2`
- Version: 6.0.0
- Copyright 2022 Fonticons, Inc.
- Source: https://fontawesome.com
- Full terms: https://fontawesome.com/license/free

Font Awesome Free is licensed in three parts:

- **Icons** (the SVG and webfont glyphs) under
  [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Attribution is
  given by this notice and by the banner retained in `fontawesome.min.css`.
- **Fonts** (the `.woff2` files) under
  [SIL OFL 1.1](https://scripts.sil.org/OFL). The files are redistributed
  unmodified, with the Reserved Font Name "Font Awesome".
- **Code** (the CSS) under the MIT License.

Only the `solid` and `brands` styles are shipped, because those are the only
ones the UI uses. The `regular` style is not included.
