# Corresponding sources and rebuilding

The portable package includes complete, unmodified source archives for Qt 6.10.3 base, imageformats, SVG and PySide/Shiboken 6.10.3 under third_party/sources. Origin URLs and SHA-256 are in source-manifest.json. Check coverage against the final Qt DLL inventory; an unaccounted module blocks release.

Obtain the application's own source from the source archive of the same version. Use Python 3.12 x64 and a dedicated environment. Install requirements-dev.lock with --require-hashes, then run scripts/build_windows.ps1 with external output directories. No signing keys, DRM or private services are required.

Qt/PySide DLLs remain dynamically linked and replaceable under _internal/PySide6 and related runtime directories. For a modified build, follow CMake/MSVC instructions in the included Qt and PySide source archives, keep ABI and architecture consistent, install the resulting Python wheels in your environment, and rebuild using the provided packaging spec. Alternatively replace compatible libraries in a copy of the portable folder. Preserve licensing and attribution when redistributing.

The build script collects license texts and library source archives outside the source checkout. Rebuilding may download official source archives at build time; the application itself has no download or upload workflow.
