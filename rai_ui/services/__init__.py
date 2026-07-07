"""Non-widget services for the RAI v3 shell.

Everything in here is Qt-core only (no QtWidgets): the background analysis
worker and the recent-files store. Widgets consume these; they never reach
back into widget land.
"""
