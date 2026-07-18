"""Wrap a standalone function sample as a stdin/stdout *program*.

TransCoder / HumanEval-X ship parallel *functions*.  To evaluate them exactly
like CodeNet, we wrap each function in a tiny driver that

  * reads one JSON value per line from standard input (one per argument),
  * calls the function,
  * prints the return value in a canonical, language-independent form.

The wrapped source is an ordinary program (``kind = "program"``), so the whole
CodeNet pipeline -- LLM prompt, execution verification, Python 2/3 fallback,
exit-status rules, statistics, ``reverify`` -- applies unchanged.  No LLM is
involved in building the wrapper.

Python / JavaScript wrappers are generic (dynamic).  C++, Java and Go wrappers
are generated type-directed from the ``declaration``.  Unsupported signatures
raise :class:`UnsupportedSignature` so the caller can skip that language.

Canonical output (identical across languages):
  bool -> ``true``/``false``   int -> decimal
  float -> 6 decimals, trailing zeros + dot stripped ("3.0"->"3", "3.5"->"3.5")
  string -> raw characters      list -> ``[e0, e1, ...]``
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


class UnsupportedSignature(Exception):
    pass


@dataclass
class T:
    kind: str                    # int | long | float | bool | str | list
    native: str                  # exact type string in the target language
    elem: Optional["T"] = None


@dataclass
class Signature:
    entry: str
    args: list[T]
    ret: T


# --- signature parsing ------------------------------------------------------
def _paren_slice(decl: str) -> tuple[str, str, str]:
    open_i = decl.find("(")
    depth, close_i = 0, -1
    for i in range(open_i, len(decl)) if open_i != -1 else []:
        if decl[i] == "(":
            depth += 1
        elif decl[i] == ")":
            depth -= 1
            if depth == 0:
                close_i = i
                break
    if open_i == -1 or close_i == -1:
        raise UnsupportedSignature(f"malformed signature: {decl!r}")
    return decl[:open_i], decl[open_i + 1 : close_i], decl[close_i + 1 :]


def _split_top(s: str) -> list[str]:
    out, depth, cur = [], 0, ""
    for ch in s:
        if ch in "<[({":
            depth += 1
        elif ch in ">])}":
            depth -= 1
        if ch == "," and depth == 0:
            out.append(cur)
            cur = ""
        else:
            cur += ch
    if cur.strip():
        out.append(cur)
    return [p.strip() for p in out if p.strip()]


def _cpp_type(s: str) -> T:
    s = s.replace("std::", "").replace("const", "").replace("&", "").strip()
    m = re.match(r"vector\s*<(.+)>$", s)
    if m:
        e = _cpp_type(m.group(1))
        return T("list", f"vector<{e.native}>", e)
    tbl = {"int": ("int", "int"), "long": ("long", "long long"), "long long": ("long", "long long"),
           "float": ("float", "float"), "double": ("float", "double"),
           "bool": ("bool", "bool"), "string": ("str", "string")}
    if s in tbl:
        k, n = tbl[s]
        return T(k, n)
    raise UnsupportedSignature(f"unsupported C++ type: {s!r}")


def _java_type(s: str) -> T:
    s = s.strip()
    m = re.match(r"(?:List|ArrayList)\s*<(.+)>$", s)
    if m:
        e = _java_type(m.group(1))
        return T("list", f"List<{_java_box(e)}>", e)
    if s.endswith("[]"):
        e = _java_type(s[:-2].strip())
        return T("list", f"{e.native}[]", e)
    tbl = {"int": ("int", "int"), "Integer": ("int", "int"), "long": ("long", "long"), "Long": ("long", "long"),
           "float": ("float", "double"), "double": ("float", "double"), "Double": ("float", "double"),
           "Float": ("float", "double"), "boolean": ("bool", "boolean"), "Boolean": ("bool", "boolean"),
           "String": ("str", "String")}
    if s in tbl:
        k, n = tbl[s]
        return T(k, n)
    raise UnsupportedSignature(f"unsupported Java type: {s!r}")


def _java_box(t: T) -> str:
    return {"int": "Integer", "long": "Long", "double": "Double", "boolean": "Boolean"}.get(t.native, t.native)


def _go_type(s: str) -> T:
    s = s.strip()
    if s.startswith("[]"):
        e = _go_type(s[2:])
        return T("list", f"[]{e.native}", e)
    tbl = {"int": ("int", "int"), "int64": ("long", "int64"), "int32": ("int", "int32"),
           "float64": ("float", "float64"), "float32": ("float", "float32"),
           "bool": ("bool", "bool"), "string": ("str", "string")}
    if s in tbl:
        k, n = tbl[s]
        return T(k, n)
    raise UnsupportedSignature(f"unsupported Go type: {s!r}")


def parse_signature(language: str, declaration: str) -> Signature:
    before, params, after = _paren_slice(declaration)
    if language == "C++":
        entry = before.split()[-1]
        ret = _cpp_type(before[: -len(entry)].strip().split()[-1])
        args = [_cpp_type(" ".join(p.split()[:-1])) for p in _split_top(params)]
    elif language == "Java":
        entry = before.split()[-1]
        ret = _java_type(before[: -len(entry)].strip().split()[-1])
        args = [_java_type(" ".join(p.split()[:-1])) for p in _split_top(params)]
    elif language == "Go":
        entry = re.search(r"func\s+(\w+)", before).group(1)
        ret = _go_type(after.strip().rstrip("{").strip())
        args = [_go_type(p.split(None, 1)[1]) for p in _split_top(params)]
    else:
        raise UnsupportedSignature(f"typed parsing unsupported for {language}")
    return Signature(entry, args, ret)


def entry_name(language: str, declaration: str, source: str) -> str:
    if language == "Python":
        m = re.search(r"def\s+(\w+)\s*\(", declaration or source)
    elif language == "JavaScript":
        m = (re.search(r"(?:const|let|var)\s+(\w+)\s*=", source)
             or re.search(r"function\s+(\w+)", source))
    else:
        return parse_signature(language, declaration).entry
    if not m:
        raise UnsupportedSignature(f"cannot find entry point ({language})")
    return m.group(1)


# ===========================================================================
_HEADER = {
    "Python": "# Auto-generated wrapper. stdin: one JSON value per line = the\n# arguments of {entry} in order. stdout: the canonical return value.\n",
    "JavaScript": "// Auto-generated wrapper. stdin: one JSON value per line = the\n// arguments of {entry} in order. stdout: the canonical return value.\n",
    "C++": "// Auto-generated wrapper. stdin: one JSON value per line = the\n// arguments of {entry} in order. stdout: the canonical return value.\n",
    "Java": "// Auto-generated wrapper. stdin: one JSON value per line = the\n// arguments of {entry} in order. stdout: the canonical return value.\n",
    "Go": "// Auto-generated wrapper. stdin: one JSON value per line = the\n// arguments of {entry} in order. stdout: the canonical return value.\n",
}


def build_wrapper(language: str, source: str, declaration: str) -> str:
    """Return a stdin/stdout program wrapping the function, or raise
    :class:`UnsupportedSignature` if it cannot be built for this language."""
    try:
        if language == "Python":
            entry = entry_name("Python", declaration, source)
            body = _PY.format(source=source.rstrip(), entry=entry)
        elif language == "JavaScript":
            entry = entry_name("JavaScript", declaration, source)
            body = _JS.format(source=source.rstrip(), entry=entry)
        elif language == "C++":
            sig = parse_signature("C++", declaration)
            entry, body = sig.entry, _cpp_wrapper(source, sig)
        elif language == "Java":
            sig = parse_signature("Java", declaration)
            entry, body = sig.entry, _java_wrapper(source, sig)
        elif language == "Go":
            sig = parse_signature("Go", declaration)
            entry, body = sig.entry, _go_wrapper(source, sig)
        else:
            raise UnsupportedSignature(f"no wrapper builder for {language}")
    except UnsupportedSignature:
        raise
    except Exception as exc:  # any parsing glitch -> treat as unsupported, skip
        raise UnsupportedSignature(f"{language} wrapper build failed: {exc}") from exc
    return _HEADER[language].format(entry=entry) + body


# --- Python / JavaScript (generic) -----------------------------------------
_PY = '''\
import sys, json

{source}

def _canon(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        s = ("%.6f" % v).rstrip("0").rstrip(".")
        return "0" if s in ("", "-0") else s
    if isinstance(v, str):
        return v
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(_canon(x) for x in v) + "]"
    if v is None:
        return "null"
    return str(v)

_args = [json.loads(l) for l in sys.stdin.read().splitlines() if l.strip() != ""]
sys.stdout.write(_canon({entry}(*_args)) + "\\n")
'''

_JS = '''\
const _fs = require('fs');

{source}

function _canon(v){{
  if (typeof v === 'boolean') return v ? 'true' : 'false';
  if (typeof v === 'number') {{
    if (Number.isInteger(v)) return String(v);
    return v.toFixed(6).replace(/0+$/, '').replace(/\\.$/, '');
  }}
  if (typeof v === 'string') return v;
  if (Array.isArray(v)) return '[' + v.map(_canon).join(', ') + ']';
  if (v === null || v === undefined) return 'null';
  return String(v);
}}

const _args = _fs.readFileSync(0,'utf8').split('\\n').filter(l => l.trim() !== '').map(l => JSON.parse(l));
process.stdout.write(_canon({entry}(..._args)) + '\\n');
'''


# --- C++ -------------------------------------------------------------------
_CPP_PRE = r"""
static std::string _trim(std::string s){size_t a=s.find_first_not_of(" \t\r\n");if(a==std::string::npos)return "";size_t b=s.find_last_not_of(" \t\r\n");return s.substr(a,b-a+1);}
static std::string _inner(std::string s){s=_trim(s);if(!s.empty()&&s.front()=='[')s=s.substr(1);if(!s.empty()&&s.back()==']')s.pop_back();return s;}
static std::vector<std::string> _elems(std::string s){std::vector<std::string> r;int d=0;std::string c;for(char ch:s){if(ch=='['||ch=='{')d++;else if(ch==']'||ch=='}')d--;if(ch==','&&d==0){r.push_back(c);c="";}else c+=ch;}if(_trim(c)!="")r.push_back(c);return r;}
static std::string _pstr(std::string s){s=_trim(s);if(s.size()>=2&&s.front()=='"'&&s.back()=='"')s=s.substr(1,s.size()-2);return s;}
static std::string _canonf(double x){char b[64];snprintf(b,sizeof b,"%.6f",x);std::string s(b);size_t dot=s.find('.');if(dot!=std::string::npos){size_t last=s.find_last_not_of('0');if(s[last]=='.')last--;s=s.substr(0,last+1);}if(s=="-0")s="0";return s;}
static std::string _c(bool v){return v?"true":"false";}
static std::string _c(int v){return std::to_string(v);}
static std::string _c(long long v){return std::to_string(v);}
static std::string _c(double v){return _canonf(v);}
static std::string _c(float v){return _canonf(v);}
static std::string _c(const std::string& v){return v;}
template<class U> static std::string _c(const std::vector<U>& v){std::string r="[";for(size_t i=0;i<v.size();++i){if(i)r+=", ";r+=_c(v[i]);}return r+"]";}
"""


def _cpp_parse(t: T, s: str, reg: dict) -> str:
    if t.kind in ("int", "long"):
        return f"({t.native})std::stoll(_trim({s}))"
    if t.kind == "float":
        return f"({t.native})std::stod(_trim({s}))"
    if t.kind == "bool":
        return f'(_trim({s})=="true")'
    if t.kind == "str":
        return f"_pstr({s})"
    if t.kind == "list":
        return f"{_cpp_list(t, reg)}({s})"
    raise UnsupportedSignature(t.kind)


def _cpp_list(t: T, reg: dict) -> str:
    if t.native in reg:
        return reg[t.native]
    name = f"_pl{len([k for k in reg if not k.startswith('__')])}"
    reg[t.native] = name
    reg["__code__"] = reg.get("__code__", "") + (
        f"static {t.native} {name}(std::string s){{{t.native} v;"
        f"for(auto& e:_elems(_inner(s)))v.push_back({_cpp_parse(t.elem, 'e', reg)});return v;}}\n"
    )
    return name


def _cpp_wrapper(source: str, sig: Signature) -> str:
    reg: dict = {}
    lines = [f"  {a.native} a{i}={_cpp_parse(a, f'L[{i}]', reg)};" for i, a in enumerate(sig.args)]
    call = f"{sig.entry}(" + ", ".join(f"a{i}" for i in range(len(sig.args))) + ")"
    main = ("int main(){std::vector<std::string> L;std::string ln;"
            'while(std::getline(std::cin,ln)){if(_trim(ln)!="")L.push_back(ln);}\n'
            + "\n".join(lines) + "\n"
            f'  std::cout<<_c({call})<<"\\n";return 0;}}\n')
    return ("#include <bits/stdc++.h>\nusing namespace std;\n" + source.rstrip() + "\n"
            + _CPP_PRE + reg.get("__code__", "") + main)


# --- Java ------------------------------------------------------------------
_JAVA_PRE = r"""
  static String _trim(String s){return s.trim();}
  static String _inner(String s){s=s.trim();if(s.startsWith("["))s=s.substring(1);if(s.endsWith("]"))s=s.substring(0,s.length()-1);return s;}
  static java.util.List<String> _elems(String s){java.util.List<String> r=new java.util.ArrayList<>();int d=0;StringBuilder c=new StringBuilder();for(char ch:s.toCharArray()){if(ch=='['||ch=='{')d++;else if(ch==']'||ch=='}')d--;if(ch==','&&d==0){r.add(c.toString());c.setLength(0);}else c.append(ch);}if(!c.toString().trim().isEmpty())r.add(c.toString());return r;}
  static String _pstr(String s){s=s.trim();if(s.length()>=2&&s.startsWith("\"")&&s.endsWith("\""))s=s.substring(1,s.length()-1);return s;}
  static String _canonf(double x){String s=String.format(java.util.Locale.ROOT,"%.6f",x);if(s.contains(".")){s=s.replaceAll("0+$","");if(s.endsWith("."))s=s.substring(0,s.length()-1);}if(s.equals("-0"))s="0";return s;}
  static String _c(boolean v){return v?"true":"false";}
  static String _c(int v){return Integer.toString(v);}
  static String _c(long v){return Long.toString(v);}
  static String _c(double v){return _canonf(v);}
  static String _c(String v){return v;}
"""


def _java_parse(t: T, s: str, reg: dict) -> str:
    if t.kind == "int":
        return f"Integer.parseInt(_trim({s}))"
    if t.kind == "long":
        return f"Long.parseLong(_trim({s}))"
    if t.kind == "float":
        return f"Double.parseDouble(_trim({s}))"
    if t.kind == "bool":
        return f'_trim({s}).equals("true")'
    if t.kind == "str":
        return f"_pstr({s})"
    if t.kind == "list":
        return f"{_java_list(t, reg)}({s})"
    raise UnsupportedSignature(t.kind)


def _java_print(t: T, expr: str, reg: dict) -> str:
    if t.kind == "list":
        return f"{_java_listprint(t, reg)}({expr})"
    return f"_c({expr})"


def _java_list(t: T, reg: dict) -> str:
    key = "P" + t.native
    if key in reg:
        return reg[key]
    name = f"_pl{len([k for k in reg if k.startswith('P')])}"
    reg[key] = name
    reg["__code__"] = reg.get("__code__", "") + (
        f"  static List<{_java_box(t.elem)}> {name}(String s){{List<{_java_box(t.elem)}> v=new java.util.ArrayList<>();"
        f"for(String e:_elems(_inner(s)))v.add({_java_parse(t.elem, 'e', reg)});return v;}}\n"
    )
    return name


def _java_listprint(t: T, reg: dict) -> str:
    key = "C" + t.native
    if key in reg:
        return reg[key]
    name = f"_cl{len([k for k in reg if k.startswith('C')])}"
    reg[key] = name
    reg["__code__"] = reg.get("__code__", "") + (
        f"  static String {name}(List<{_java_box(t.elem)}> v){{StringBuilder b=new StringBuilder(\"[\");"
        f"for(int i=0;i<v.size();i++){{if(i>0)b.append(\", \");b.append({_java_print(t.elem, 'v.get(i)', reg)});}}"
        f"b.append(\"]\");return b.toString();}}\n"
    )
    return name


def _java_wrapper(source: str, sig: Signature) -> str:
    reg: dict = {}
    lines = [f"    {a.native} a{i}={_java_parse(a, f'L.get({i})', reg)};" for i, a in enumerate(sig.args)]
    call = f"new Solution().{sig.entry}(" + ", ".join(f"a{i}" for i in range(len(sig.args))) + ")"
    printed = _java_print(sig.ret, call, reg)
    body = ("import java.util.*;\n" + source.rstrip() + "\n"
            "public class Main {\n" + _JAVA_PRE + reg.get("__code__", "")
            + "  public static void main(String[] x) throws Exception {\n"
            "    java.util.Scanner sc=new java.util.Scanner(System.in);List<String> L=new ArrayList<>();"
            "while(sc.hasNextLine()){String l=sc.nextLine();if(!l.trim().isEmpty())L.add(l);}\n"
            + "\n".join(lines) + "\n"
            f"    System.out.println({printed});\n  }}\n}}\n")
    return body


# --- Go --------------------------------------------------------------------
_GO_PRE = r"""
func _trim(s string) string { return strings.TrimSpace(s) }
func _inner(s string) string { s = _trim(s); s = strings.TrimPrefix(s, "["); s = strings.TrimSuffix(s, "]"); return s }
func _elems(s string) []string {
	r := []string{}
	d := 0
	cur := ""
	for _, ch := range s {
		if ch == '[' || ch == '{' { d++ } else if ch == ']' || ch == '}' { d-- }
		if ch == ',' && d == 0 { r = append(r, cur); cur = "" } else { cur += string(ch) }
	}
	if _trim(cur) != "" { r = append(r, cur) }
	return r
}
func _canonf(x float64) string {
	s := strconv.FormatFloat(x, 'f', 6, 64)
	if strings.Contains(s, ".") { s = strings.TrimRight(s, "0"); s = strings.TrimSuffix(s, ".") }
	if s == "-0" { s = "0" }
	return s
}
func _cbool(v bool) string { if v { return "true" }; return "false" }
func _cstr(v string) string { return v }
"""


def _go_parse(t: T, s: str, reg: dict) -> str:
    if t.kind == "int":
        return f"func() int {{ n,_ := strconv.Atoi(_trim({s})); return n }}()"
    if t.kind == "long":
        return f"func() int64 {{ n,_ := strconv.ParseInt(_trim({s}),10,64); return n }}()"
    if t.kind == "float":
        return f"func() {t.native} {{ n,_ := strconv.ParseFloat(_trim({s}),64); return {t.native}(n) }}()"
    if t.kind == "bool":
        return f'(_trim({s}) == "true")'
    if t.kind == "str":
        return f"_gostr({s})"
    if t.kind == "list":
        return f"{_go_list(t, reg)}({s})"
    raise UnsupportedSignature(t.kind)


def _go_list(t: T, reg: dict) -> str:
    key = "P" + t.native
    if key in reg:
        return reg[key]
    name = f"_pl{len([k for k in reg if k.startswith('P')])}"
    reg[key] = name
    reg["__code__"] = reg.get("__code__", "") + (
        f"func {name}(s string) {t.native} {{ v := {t.native}{{}}; "
        f"for _, e := range _elems(_inner(s)) {{ v = append(v, {_go_parse(t.elem, 'e', reg)}) }}; return v }}\n"
    )
    return name


def _go_print(t: T, expr: str, reg: dict) -> str:
    if t.kind == "bool":
        return f"_cbool({expr})"
    if t.kind in ("int", "long"):
        return f"strconv.FormatInt(int64({expr}), 10)"
    if t.kind == "float":
        return f"_canonf(float64({expr}))"
    if t.kind == "str":
        return f"_cstr({expr})"
    if t.kind == "list":
        return f"{_go_listprint(t, reg)}({expr})"
    raise UnsupportedSignature(t.kind)


def _go_listprint(t: T, reg: dict) -> str:
    key = "C" + t.native
    if key in reg:
        return reg[key]
    name = f"_cl{len([k for k in reg if k.startswith('C')])}"
    reg[key] = name
    reg["__code__"] = reg.get("__code__", "") + (
        f"func {name}(v {t.native}) string {{ r := \"[\"; for i := range v {{ if i>0 {{ r += \", \" }}; "
        f"r += {_go_print(t.elem, 'v[i]', reg)} }}; return r + \"]\" }}\n"
    )
    return name


def _go_wrapper(source: str, sig: Signature) -> str:
    # HumanEval-X Go sources omit the package clause; strip one if present so we
    # don't emit a duplicate.
    source = re.sub(r"(?m)^\s*package\s+\w+\s*$\n?", "", source, count=1)
    reg: dict = {}
    lines = [f"\ta{i} := {_go_parse(a, f'L[{i}]', reg)}" for i, a in enumerate(sig.args)]
    call = f"{sig.entry}(" + ", ".join(f"a{i}" for i in range(len(sig.args))) + ")"
    printed = _go_print(sig.ret, call, reg)
    # Merge imports: collect what the source's import declarations already pull
    # in, then add only the packages we need that are not already present.
    present: set[str] = set(re.findall(r'import\s+"([^"]+)"', source))
    for blk in re.findall(r"import\s*\((.*?)\)", source, re.S):
        present |= set(re.findall(r'"([^"]+)"', blk))
    add = "".join(f'\t"{p}"\n' for p in ("bufio", "fmt", "os", "strconv", "strings") if p not in present)
    strhelper = 'func _gostr(s string) string { s = _trim(s); if len(s) >= 2 && s[0] == \'"\' && s[len(s)-1] == \'"\' { s = s[1:len(s)-1] }; return s }\n'
    main = ("func main() {\n\tsc := bufio.NewScanner(os.Stdin)\n\tsc.Buffer(make([]byte, 1<<20), 1<<20)\n"
            "\tL := []string{}\n\tfor sc.Scan() { if _trim(sc.Text()) != \"\" { L = append(L, sc.Text()) } }\n"
            + "\n".join(lines) + "\n"
            f"\tfmt.Println({printed})\n}}\n")
    return ("package main\n" + f"import (\n{add})\n"
            + source.rstrip() + "\n" + _GO_PRE + strhelper + reg.get("__code__", "") + main)
