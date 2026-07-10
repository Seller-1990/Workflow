# Context7 文档复核摘要

## Sources

- Qt for Python / PySide6: `/websites/doc_qt_io_qtforpython-6`
  - https://doc.qt.io/qtforpython-6/examples/example_widgets_thread_signals.html
  - https://doc.qt.io/qtforpython-6/PySide6/QtCore/QThread.html
- SQLAlchemy ORM 2.0: `/websites/sqlalchemy_en_20_orm`
  - https://docs.sqlalchemy.org/en/20/orm/cascades.html
  - https://docs.sqlalchemy.org/en/20/orm/large_collections.html
- PyInstaller stable: `/websites/pyinstaller_en_stable`
  - https://pyinstaller.org/en/stable/hooks.html
  - https://pyinstaller.org/en/stable/runtime-information.html
  - https://pyinstaller.org/en/stable/when-things-go-wrong.html

## Findings

- PySide6 recommends worker objects moved to `QThread`, with worker signals connected to UI slots. Cross-thread signal handling should be queued so UI mutation happens in the receiver thread.
- SQLAlchemy ORM delete cascades on `Session.delete()` are instance-oriented. Bulk deletes do not use ORM cascade behavior. For large child collections, database `ON DELETE CASCADE` plus matching relationship cascade and `passive_deletes=True` reduces ORM-side DELETE/load work.
- PyInstaller supports using spec files for hidden imports and package data collection. Current specs already use explicit hidden imports and `collect_data_files("certifi")`; remaining improvements should focus on stale metadata and package self-check consistency, not replacing this mechanism.
