"""
Typo tolerance and autocomplete, both built on the index's vocabulary
(every distinct word that appears in any document).

The vocabulary is loaded from SQLite once and cached in memory. The cache
is keyed on the database file's modification time, so uploading or
deleting a document automatically triggers a reload on the next request.
"""
import os
import re
import sqlite3
import bisect

# ── Edit distance ──


def edit_distance(a, b, max_dist):
    """
    Optimal String Alignment distance: the number of single-character
    insertions, deletions, substitutions, or swaps of two neighbouring
    letters needed to turn `a` into `b`.

    Swaps count as 1 edit because they are the most common typing mistake:
    plain Levenshtein says "pyhton" -> "python" is 2 edits, this says 1.

    Returns max_dist + 1 as soon as the answer is known to exceed max_dist,
    which skips most of the work for words that are clearly different.
    """
    if abs(len(a) - len(b)) > max_dist:
        return max_dist + 1

    # rows of the dynamic programming table: prev2 = i-2, prev = i-1, cur = i
    prev2 = None
    prev = list(range(len(b) + 1))

    for i in range(1, len(a) + 1):
        cur = [i] + [0] * len(b)
        row_min = cur[0]
        for j in range(1, len(b) + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            cur[j] = min(
                prev[j] + 1,         # delete from a
                cur[j - 1] + 1,      # insert into a
                prev[j - 1] + cost,  # substitute
            )
            if (i > 1 and j > 1 and a[i - 1] == b[j - 2]
                    and a[i - 2] == b[j - 1]):
                cur[j] = min(cur[j], prev2[j - 2] + 1)  # swap neighbours
            row_min = min(row_min, cur[j])

        # every later row is >= this row's minimum, so we can stop early
        if row_min > max_dist:
            return max_dist + 1
        prev2, prev = prev, cur

    return prev[len(b)]


def letter_pairs(word):
    """
    Overlapping two-letter chunks, padded so the first and last letters
    count too: "cat" -> ["^c", "ca", "at", "t$"].
    """
    padded = f"^{word}$"
    return [padded[i:i + 2] for i in range(len(padded) - 1)]


def allowed_typos(word):
    # short words get less slack: "cat" -> "car" is 1 edit but a different word
    if len(word) <= 2:
        return 0
    if len(word) <= 5:
        return 1
    return 2


# ── Vocabulary ──


class Vocabulary:
    def __init__(self, db_path):
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # df = number of documents containing the word
        # cf = total number of times it appears across all documents
        cursor.execute("""
            SELECT word, COUNT(DISTINCT doc_id), SUM(frequency)
            FROM index_entries GROUP BY word
        """)
        self.df = {}
        self.cf = {}
        for word, df, cf in cursor.fetchall():
            self.df[word] = df
            self.cf[word] = cf

        # sorted list lets us find every word with a given prefix using
        # binary search in O(log n), instead of scanning the whole vocabulary
        self.sorted_words = sorted(self.df)

        # words grouped by length, so spell correction only compares
        # against words that are close enough in length to possibly match
        self.by_length = {}
        for word in self.sorted_words:
            self.by_length.setdefault(len(word), []).append(word)

        # letter-pair index: "th" -> {words containing "th"}. Used to skip
        # words that can't possibly be within a couple of edits of the typo
        self.pair_index = {}
        for word in self.sorted_words:
            for pair in set(letter_pairs(word)):
                self.pair_index.setdefault(pair, []).append(word)

        # bigram counts ("machine" followed by "learning") make autocomplete
        # aware of the previous word you typed
        self.bigrams = {}
        cursor.execute("SELECT text FROM lines")
        for (text,) in cursor.fetchall():
            words = [w for w in (clean(t) for t in text.split()) if len(w) >= 2]
            for first, second in zip(words, words[1:]):
                following = self.bigrams.setdefault(first, {})
                following[second] = following.get(second, 0) + 1

        conn.close()

    def __contains__(self, word):
        return word in self.df

    def __len__(self):
        return len(self.df)

    # ── Spell correction ──

    def correct(self, word):
        """Best replacement for a word that isn't in the index, or None."""
        if word in self.df:
            return None

        max_dist = allowed_typos(word)
        if max_dist == 0:
            return None

        # Each edit can break at most 3 of the typo's letter pairs (a swap
        # "ab" -> "ba" breaks 3, other edits break 2 or fewer). So a real
        # match must still share at least  pairs - 3 * max_dist  of them.
        # Counting shared pairs is much cheaper than computing edit distance,
        # so only words that pass this check get the full comparison.
        pairs = set(letter_pairs(word))
        min_shared = len(pairs) - 3 * max_dist

        if min_shared >= 1:
            shared = {}
            for pair in pairs:
                for candidate in self.pair_index.get(pair, ()):
                    shared[candidate] = shared.get(candidate, 0) + 1
            candidates = [
                c for c, n in shared.items()
                if n >= min_shared and abs(len(c) - len(word)) <= max_dist
            ]
        else:
            # very short typos: the filter can't rule anything out
            candidates = [
                c for length in range(len(word) - max_dist, len(word) + max_dist + 1)
                for c in self.by_length.get(length, [])
            ]

        best = None
        best_key = None

        for candidate in candidates:
            dist = edit_distance(word, candidate, max_dist)
            if dist > max_dist:
                continue
            # fewest edits wins; ties go to the word in the most documents,
            # then the one sharing the first letter (people rarely mistype it)
            key = (dist, -self.df[candidate], candidate[0] != word[0], candidate)
            if best_key is None or key < best_key:
                best, best_key = candidate, key

        return best

    # ── Autocomplete ──

    def words_with_prefix(self, prefix):
        start = bisect.bisect_left(self.sorted_words, prefix)
        # every word starting with prefix sorts before prefix + the highest character
        end = bisect.bisect_left(self.sorted_words, prefix + "\uffff")
        return self.sorted_words[start:end]

    def complete(self, prefix, previous_word=None, limit=6):
        candidates = self.words_with_prefix(prefix)
        if not candidates:
            return []

        following = self.bigrams.get(previous_word, {}) if previous_word else {}

        def rank(word):
            # words that actually follow the previous word come first,
            # then the most frequent words overall
            return (-following.get(word, 0), -self.cf[word], word)

        return sorted(candidates, key=rank)[:limit]


def clean(word):
    return re.sub(r'[^a-z0-9]', '', word.lower())


# ── Cache ──

_cache = {"key": None, "vocab": None}


def get_vocabulary(db_path):
    try:
        stat = os.stat(db_path)
    except FileNotFoundError:
        return None
    key = (db_path, stat.st_mtime_ns, stat.st_size)
    if _cache["key"] != key:
        _cache["vocab"] = Vocabulary(db_path)
        _cache["key"] = key
    return _cache["vocab"]
