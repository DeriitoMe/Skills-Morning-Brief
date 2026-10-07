"""Compatibility entry point using the authenticated reader service."""
from .core import ROOT
from .shelf_server import ShelfService, make_shelf_handler, serve_shelf


def make_handler(root, port, store=None):
    return make_shelf_handler(ShelfService(root, store), port)


def serve(root=ROOT, port=8765):
    return serve_shelf(root, port)
