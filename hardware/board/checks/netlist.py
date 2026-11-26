"""Read a KiCad (version D) netlist into plain dicts, independent of SKiDL."""

import copy
import re

TOKEN = re.compile(r'\(|\)|"(?:[^"\\]|\\.)*"|[^\s()"]+')


def sexpr(text):
    stack = [[]]
    for tok in TOKEN.findall(text):
        if tok == "(":
            stack.append([])
        elif tok == ")":
            done = stack.pop()
            stack[-1].append(done)
        else:
            stack[-1].append(tok[1:-1] if tok.startswith('"') else tok)
    return stack[0][0]


def kids(node, key):
    return [c for c in node[1:] if isinstance(c, list) and c and c[0] == key]


def one(node, key, default=None):
    k = kids(node, key)
    return k[0][1] if k and len(k[0]) > 1 else default


class Netlist:
    """comps: ref -> {value, footprint, fields}; nets: name -> set of (ref, pin)."""

    def __init__(self, comps, nets):
        self.comps, self.nets = comps, nets

    @classmethod
    def load(cls, path):
        with open(path) as fh:
            root = sexpr(fh.read())
        comps = {}
        refs = []
        for c in kids(kids(root, "components")[0], "comp"):
            ref = one(c, "ref")
            refs.append(ref)
            fields = {}
            for fs in kids(c, "fields"):
                for f in kids(fs, "field"):
                    fields[one(f, "name")] = f[2] if len(f) > 2 else ""
            comps[ref] = {"value": one(c, "value"), "footprint": one(c, "footprint"), "fields": fields}
        nets = {}
        for n in kids(kids(root, "nets")[0], "net"):
            nets[one(n, "name")] = {(one(x, "ref"), one(x, "pin")) for x in kids(n, "node")}
        nl = cls(comps, nets)
        nl.refs = refs  # in file order, duplicates kept (for the designator check)
        return nl

    def copy(self):
        c = Netlist(copy.deepcopy(self.comps), copy.deepcopy(self.nets))
        c.refs = list(self.refs)
        return c

    def net_of(self, ref, pin):
        """Name of the net holding (ref, pin), or None if the pin is unconnected."""
        for name, nodes in self.nets.items():
            if (ref, pin) in nodes:
                return name
        return None

    def nodes(self, ref, pin):
        name = self.net_of(ref, pin)
        return self.nets[name] if name else set()

    def pins_of(self, ref):
        return {p: name for name, nodes in self.nets.items() for r, p in nodes if r == ref}

    def find(self, mpn_prefix):
        return sorted(r for r, c in self.comps.items() if c["fields"].get("MPN", "").startswith(mpn_prefix))

    # mutation helpers (tests)
    def move(self, ref, pin, net):
        for nodes in self.nets.values():
            nodes.discard((ref, pin))
        if net is not None:
            self.nets.setdefault(net, set()).add((ref, pin))

    def add_part(self, ref, footprint, mpn, pins):
        self.comps[ref] = {"value": mpn, "footprint": footprint, "fields": {"MPN": mpn, "LCSC": "C1"}}
        self.refs.append(ref)
        for pin, net in pins.items():
            self.move(ref, pin, net)
