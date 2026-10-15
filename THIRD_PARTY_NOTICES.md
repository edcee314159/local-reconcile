# Third-party software

The MIT license applies to Local Reconcile's own code. It does not relicense dependencies.

The portable distribution includes Python 3.12, PySide6 Essentials 6.10.3 / Shiboken6 6.10.3 / Qt 6.10.3, openpyxl 3.1.5, et_xmlfile 2.0.0 and defusedxml 0.7.1, plus relevant runtime components. The collected DLL inventory is generated with the release.

- Python and bundled components: PSF license and notices, see the included Python license.
- PySide6 / Shiboken / used Qt libraries: applicable LGPLv3 or other upstream license notices. The application imports QtCore, QtGui and QtWidgets. Collected plugins may bring additional Qt modules; inventory and corresponding source archives accompany the bundle.
- openpyxl and et_xmlfile: upstream MIT license texts.
- defusedxml: upstream PSF license text.
- Build tools such as PyInstaller are not the application's license.

See third_party/licenses for upstream texts and third_party/sources for unmodified corresponding Qt/PySide source archives, origin URLs and SHA-256. Qt libraries remain separate DLLs. See third_party/SOURCE_INFO.md for rebuilding and replacing libraries. There are no terms preventing debugging modifications or replacing LGPL libraries.

System fonts are used from the user's Windows installation. No Microsoft or other font file is redistributed.

Upstream:
https://www.qt.io/development/open-source-lgpl-obligations
https://pyinstaller.org/en/stable/license.html
https://openpyxl.readthedocs.io/
