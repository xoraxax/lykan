import collections
import hashlib
from multiprocessing.dummy.connection import Queue, Connection


def toposort(players):
    cards = []
    for player in players:
        if player.is_alive:
            cards.append(player.role_card)
    tags = collections.defaultdict(list)
    for card in cards:
        for tag in card.TAGS:
            tags[tag].append(card)
        tags["HAS_PREPARE" + ("" if hasattr(card, "prepare") else "_NOT")].append(card)
    deps = collections.defaultdict(set)
    for card in cards:
        for tag in card.RUNS_AFTER + (["HAS_PREPARE"] if not hasattr(card, "prepare") else []):
            deps[card].update(tags[tag])
        deps[card]
    for k, v in deps.items():
        v.discard(k)
    while True:
        ordered = set(item for item, dep in deps.items() if not dep)
        if not ordered:
            break
        yield ordered
        deps = {item: (dep - ordered) for item, dep in deps.items() if item not in ordered}
    if deps:
        raise Exception("Circular dependency (%r)" % (deps,))


def gen_hash(text):
    md = hashlib.md5()
    md.update(text.encode("utf-8"))
    return md.hexdigest()


def check_vote(amongst, poll_result):
    cnt = collections.Counter(poll_result.values())
    common = cnt.most_common(2)
    if len(common) < 2 or common[0][1] >= len(amongst) / 2:
        return common[0][0]


def Pipe(buffer_size=4):
    a, b = Queue(buffer_size), Queue(buffer_size)
    return Connection(a, b), Connection(b, a)
