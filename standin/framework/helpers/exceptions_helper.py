"""Exception helpers shared across areas."""


def open_exception_page(nav, name):
   """Open an exception's editor from the list (also defined on the exceptions area base)."""
   exceptions = nav.exceptions.list
   exceptions.open()
   exceptions.open_exception(name)
   return nav.exceptions.editor
