"""File policies: building test files from a description, and the download / view pipeline.

Pure functions, testable without a server. Everything is fake and deterministic:

- File types are named by extension. Content is text with a type header (``%FAKE-PDF``,
  ``MZ-FAKE`` ...). Archives are real zip files (stdlib ``zipfile``). An encrypted file wraps
  its inner bytes behind a password hash.
- Malware scanning knows one invented signature (``SIGNATURE``) and a SHA-256 blocklist.
- DLP rules are regexes over the decoded text of the file (and of every archive member).
- Downloads come in two modes: ``converted`` (a safe copy: active content removed) and
  ``original``. A policy may allow only the converted copy.

A file description (seeded under ``site.files``)::

   {"name": "report.pdf", "content": "text ...", "active": "<script>...</script>",
    "password": "pw", "members": [ ...descriptions... ]}

``members`` makes a zip archive; ``password`` makes the file encrypted.
"""

import base64
import copy
import hashlib
import io
import re
import zipfile

SIGNATURE = "T2T-FAKE-MALWARE-SIGNATURE"  # invented; not a real antivirus test string
ENCRYPTED_HEADER = b"T2T-ENCRYPTED\n"
HEADERS = {
   "pdf": "%FAKE-PDF\n",
   "docx": "FAKE-DOCX\n",
   "xlsx": "FAKE-XLSX\n",
   "exe": "MZ-FAKE\n",
   "html": "",
   "txt": "",
}
FILE_TYPES = (*HEADERS, "zip")
DECISIONS = ("allowed", "converted", "blocked", "password_required")

DEFAULT_FILE_POLICY = {
   "downloads": {"default": "allow", "types": {}},  # type -> allow | block | sanitize
   "scanning": {"enabled": True, "hash_blocklist": []},
   "dlp": [],  # [{"name", "pattern", "action": block | log}]
   "archives": {"inspect": True, "max_depth": 2},
   "encrypted": "prompt",  # prompt | block | allow
   "originals": "allow",  # allow | converted_only
}
_ACTIVE = re.compile(r"<script\b.*?</script>", re.IGNORECASE | re.DOTALL)


class FileError(ValueError):
   """A bad file description or request."""


def file_type(name):
   return name.rsplit(".", 1)[-1].lower() if "." in name else ""


def build(spec):
   """The bytes of a described file."""
   name = spec["name"]
   kind = file_type(name)
   if kind not in FILE_TYPES:
      raise FileError(f"Unknown file type '{kind}'")
   if kind == "zip":
      buffer = io.BytesIO()
      with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
         for member in spec.get("members", []):
            archive.writestr(member["name"], build(member))
      data = buffer.getvalue()
   else:
      data = (HEADERS[kind] + spec.get("content", "") + spec.get("active", "")).encode("utf-8")
   if spec.get("password"):
      digest = hashlib.sha256(spec["password"].encode("utf-8")).hexdigest().encode("ascii")
      data = ENCRYPTED_HEADER + digest + b"\n" + base64.b64encode(data)
   return data


def sha256(data):
   return hashlib.sha256(data).hexdigest()


def file_policy(policy):
   """The file-policy sections of a tenant policy, with defaults for missing ones."""
   merged = copy.deepcopy(DEFAULT_FILE_POLICY)
   for key in merged:
      if key in policy:
         merged[key] = copy.deepcopy(policy[key])
   return merged


def evaluate(policy, name, data, mode="converted", password=None):
   """The download verdict: ``{"file", "mode", "decision", "reason", "findings"}``."""
   if mode not in ("converted", "original"):
      raise FileError(f"Unknown download mode '{mode}'")
   rules = file_policy(policy)
   verdict = {"file": name, "mode": mode, "decision": "allowed", "reason": "", "findings": []}

   def block(reason):
      verdict.update(decision="blocked", reason=reason)
      return verdict

   if data.startswith(ENCRYPTED_HEADER):
      if rules["encrypted"] == "block":
         return block("encrypted files are blocked")
      if rules["encrypted"] == "allow":
         verdict["findings"].append("encrypted: not inspected")
         return _finish(rules, name, verdict, mode)
      if password is None:
         verdict.update(decision="password_required", reason="enter the file's password")
         return verdict
      data = _decrypt(data, password)
      if data is None:
         return block("wrong password")
   problem = _inspect(rules, name, data, depth=0, findings=verdict["findings"])
   if problem:
      return block(problem)
   return _finish(rules, name, verdict, mode)


def view(policy, name, data, password=None):
   """Safe viewing: a read-only rendering with active content removed (or the verdict)."""
   verdict = evaluate(policy, name, data, "converted", password)
   if verdict["decision"] in ("blocked", "password_required"):
      return {"mode": "unavailable", "content": "", "verdict": verdict}
   if data.startswith(ENCRYPTED_HEADER):
      data = _decrypt(data, password) or b""
   if file_type(name) == "zip":
      with zipfile.ZipFile(io.BytesIO(data)) as archive:
         content = "\n".join(archive.namelist())
   else:
      content = _strip_active(_text(name, data))
   return {"mode": "read-only", "content": content, "verdict": verdict}


def _finish(rules, name, verdict, mode):
   kind = file_type(name)
   action = rules["downloads"]["types"].get(kind, rules["downloads"]["default"])
   if action == "block":
      verdict.update(decision="blocked", reason=f"{kind} files are blocked")
   elif mode == "original" and rules["originals"] == "converted_only":
      verdict.update(decision="blocked", reason="only the converted copy may be downloaded")
   elif action == "sanitize" or mode == "converted":
      verdict.update(decision="converted", reason="active content removed")
   return verdict


def _inspect(rules, name, data, depth, findings):
   """The first reason to block this file (or archive member), or ''."""
   scanning = rules["scanning"]
   if scanning["enabled"]:
      if SIGNATURE.encode("ascii") in data:
         return f"malware signature found in {name}"
      if sha256(data) in scanning["hash_blocklist"]:
         return f"blocked hash: {name}"
   if file_type(name) == "zip":
      archives = rules["archives"]
      if not archives["inspect"]:
         findings.append(f"archive not inspected: {name}")
         return ""
      if depth >= archives["max_depth"]:
         return f"archive nested too deeply: {name}"
      with zipfile.ZipFile(io.BytesIO(data)) as archive:
         for member in archive.namelist():
            problem = _inspect(rules, f"{name}/{member}", archive.read(member), depth + 1, findings)
            if problem:
               return problem
      return ""
   text = _text(name, data)
   for rule in rules["dlp"]:
      if re.search(rule["pattern"], text):
         if rule.get("action", "block") == "block":
            return f"DLP rule '{rule['name']}' matched in {name}"
         findings.append(f"DLP rule '{rule['name']}' logged in {name}")
   return ""


def _decrypt(data, password):
   _, digest, payload = data.split(b"\n", 2)
   expected = hashlib.sha256(password.encode("utf-8")).hexdigest().encode("ascii")
   return base64.b64decode(payload) if digest == expected else None


def _text(name, data):
   text = data.decode("utf-8", errors="replace")
   header = HEADERS.get(file_type(name), "")
   return text.removeprefix(header)


def _strip_active(text):
   return _ACTIVE.sub("", text)
