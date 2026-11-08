# dmgbuild settings (run through make_dmg.py, which passes the -D values).
import os.path

app = defines["app"]        # noqa: F821  (dmgbuild injects `defines`)
helper = defines["helper"]  # noqa: F821

format = "UDZO"
size = None
files = [app, helper]
symlinks = {}
background = defines["background"]  # noqa: F821
window_rect = ((200, 120), (720, 440))  # content size matches background.tiff
icon_size = 160
text_size = 14
icon_locations = {
    os.path.basename(app): (170, 200),
    os.path.basename(helper): (550, 200),
}
show_status_bar = False
show_tab_view = False
show_toolbar = False
show_pathbar = False
show_sidebar = False
default_view = "icon-view"
arrange_by = None
