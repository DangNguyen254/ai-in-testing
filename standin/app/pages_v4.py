"""HTML pages for file policies and the browsing agent (stable element ids for page objects).

- ``/files``: the download center (files on the fake external site)
- ``/files/<name>/download?mode=converted|original``: the verdict (password form if needed)
- ``/files/<name>/view``: safe viewing (read-only, active content removed)
- ``/settings/downloads``: the download-policy editor (object save, then the top bar)
- ``/agent``: the agent console; ``/settings/agent``: the injection guard (applied at once)
"""

from html import escape
from urllib.parse import quote

POLICY_TYPES = ("pdf", "docx", "xlsx", "exe", "html", "txt", "zip")
TYPE_ACTIONS = ("allow", "block", "sanitize")


def _options(values, selected):
   return "".join(
      f'<option value="{escape(v)}"{" selected" if v == selected else ""}>{escape(v)}</option>'
      for v in values
   )


def download_center(store, tenant_id):
   rows = "".join(
      f'<li class="file-row"><span class="file-name">{escape(name)}</span> '
      f'<a class="file-download" href="/files/{quote(name)}/download?mode=converted">Download</a> '
      f'<a class="file-original" href="/files/{quote(name)}/download?mode=original">Original</a> '
      f'<a class="file-view" href="/files/{quote(name)}/view">View</a></li>'
      for name in sorted(store.site["files"])
   )
   return "Downloads", f'<ul id="file-list">{rows}</ul>'


def verdict_page(name, verdict):
   findings = "".join(f'<li class="finding">{escape(f)}</li>' for f in verdict["findings"])
   body = (
      f'<div id="verdict-file">{escape(name)}</div>'
      f'<div id="verdict">{escape(verdict["decision"])}</div>'
      f'<div id="verdict-mode">{escape(verdict["mode"])}</div>'
      f'<div id="verdict-reason">{escape(verdict["reason"])}</div>'
      f'<ul id="findings">{findings}</ul>'
   )
   if verdict["decision"] == "password_required":
      body += (
         f'<form method="post" action="/files/{quote(name)}/download">'
         f'<input type="hidden" name="mode" value="{escape(verdict["mode"])}">'
         '<input id="file-password" name="password" type="password">'
         '<button id="password-submit">Open</button></form>'
      )
   return "Download", body


def viewer_page(name, result):
   verdict = result["verdict"]
   body = (
      f'<div id="viewer-file">{escape(name)}</div>'
      f'<div id="viewer-mode">{escape(result["mode"])}</div>'
      f'<pre id="viewer-content">{escape(result["content"])}</pre>'
      f'<div id="verdict">{escape(verdict["decision"])}</div>'
      f'<div id="verdict-reason">{escape(verdict["reason"])}</div>'
   )
   return "Viewer", body


def download_policy_page(policy):
   downloads = policy["downloads"]
   types = "".join(
      f'<label>{t}<select id="type-{t}" name="type-{t}">'
      f"{_options(('default', *TYPE_ACTIONS), downloads['types'].get(t, 'default'))}"
      "</select></label>"
      for t in POLICY_TYPES
   )
   checked = " checked" if policy["scanning"]["enabled"] else ""
   inspect = " checked" if policy["archives"]["inspect"] else ""
   body = (
      '<form method="post" action="/settings/downloads">'
      f'<select id="download-default" name="default">'
      f"{_options(('allow', 'block', 'sanitize'), downloads['default'])}</select>"
      f"{types}"
      f'<select id="encrypted-files" name="encrypted">'
      f"{_options(('prompt', 'block', 'allow'), policy['encrypted'])}</select>"
      f'<select id="originals" name="originals">'
      f"{_options(('allow', 'converted_only'), policy['originals'])}</select>"
      f'<input id="scanning-enabled" name="scanning" type="checkbox"{checked}>'
      f'<input id="archive-inspect" name="inspect" type="checkbox"{inspect}>'
      f'<input id="archive-depth" name="max_depth" value="{policy["archives"]["max_depth"]}">'
      '<button id="policy-save">Save policy</button></form>'
   )
   return "Download policy", body


def file_policy_changes(form, current):
   """The policy sections the editor's form sets (unknown types fall back to the default)."""
   types = {
      t: form[f"type-{t}"] for t in POLICY_TYPES if form.get(f"type-{t}", "default") in TYPE_ACTIONS
   }
   depth = form.get("max_depth", "")
   return {
      "downloads": {"default": form.get("default", "allow"), "types": types},
      "encrypted": form.get("encrypted", "prompt"),
      "originals": form.get("originals", "allow"),
      "scanning": {**current["scanning"], "enabled": "scanning" in form},
      "archives": {
         "inspect": "inspect" in form,
         "max_depth": int(depth) if depth.isdigit() else current["archives"]["max_depth"],
      },
   }


def agent_console(pages, task=None):
   options = _options(sorted(pages), task["start_page"] if task else "")
   body = (
      '<form method="post" action="/agent/run">'
      '<input id="agent-goal" name="goal">'
      f'<select id="agent-start" name="start_page">{options}</select>'
      '<button id="agent-run">Run</button></form>'
   )
   if task is not None:
      actions = "".join(f'<li class="agent-action">{escape(a)}</li>' for a in task["actions"])
      flags = "".join(f'<li class="agent-flag">{escape(f)}</li>' for f in task["flags"])
      body += (
         f'<div id="agent-status">{escape(task["status"])}</div>'
         f'<ul id="agent-actions">{actions}</ul><ul id="agent-flags">{flags}</ul>'
      )
   return "Agent", body


def agent_settings_page(settings):
   checked = " checked" if settings["agent"]["injection_guard"] else ""
   body = (
      '<form method="post" action="/settings/agent">'
      f'<input id="injection-guard" name="injection_guard" type="checkbox"{checked}>'
      '<button id="agent-settings-save">Apply</button></form>'
   )
   return "Agent settings", body
