import json
import math
from riv_exceptions import InternalError, RivuletSyntaxError
# pylint: disable=locally-disabled, fixme, line-too-long

VERSION = "0.1"

def _chars_in_list(list1, list2):
    retset = []
    for val in list1:
        retset += [i for i in range(len(list2)) if list2[i] == val]
    return retset

OPPOSITE_DIR = {
    "up": "down",
    "down": "up",
    "right": "left",
    "left": "right"
}

class Parser:
    "Parser for the Rivulet esolang"

    def __init__(self):
        with open('_lexicon.json', encoding='utf-8') as lex:
            self.lexicon = json.load(lex)
        with open('_commands.json', encoding='utf-8') as cmds:
            self.command_map = json.load(cmds)

        # convert all directions to lists (some are just strings)
        for s in self.lexicon:
            for r in s["readings"]:
                if not isinstance(r["dir"], list):
                    r["dir"] = [r["dir"]]

        self.primes = []


    def get_symbol_by_name(self, name:str):
        "Returns symbol representation and readings for a given name"
        retlist = []

        for ltr in self.lexicon:
            if ltr["name"] == name:
                retlist += ltr["symbol"]

        return retlist


    def _get_neighbor(self, x, y, dirtn, glyph, include_coords=False):
        if dirtn == "up" and y > 0:
            if include_coords:
                return {"symbol": glyph[y-1][x], "x": x, "y": y-1}
            return glyph[y-1][x]
        elif dirtn == "left" and x > 0:
            if include_coords:
                return {"symbol": glyph[y][x-1], "x": x-1, "y": y}
            return glyph[y][x-1]
        elif dirtn == "down" and y < len(glyph)-1:
            if include_coords:
                return {"symbol": glyph[y+1][x], "x": x, "y": y+1}
            return glyph[y+1][x]
        elif dirtn == "right" and x < len(glyph[y])-1:
            # this assumes the glyph is a perfect rect
            if include_coords:
                return {"symbol": glyph[y][x+1], "x": x+1, "y": y}
            return glyph[y][x+1]
        return None


    def _find_successful_matches(self, x, y, glyph, readings):
        "Find directions where there is a continuing character on the other side of a sign"

        successful_matches = []

        # assuming only one reading of this kind
        reading = [r for r in readings \
                if r["pos"] == "corner" \
                or r["pos"] == "continue" \
                or r["type"] == "question_marker"]

        if not reading:
            return None

        for direction in reading[0]["dir"]:
            neighbor = self._get_neighbor(x, y, direction, glyph)
            if not neighbor:
                continue

            # all neighbor's readings
            nbr_reads = [l["readings"] for l in self.lexicon if neighbor in l["symbol"]]
            if not nbr_reads:
                continue

            # we ignore pre_start as it is decorative and adds no value
            # NOTE: a pre_start may become required for left/right hooks
            # as the language develops (need to see how much it affects
            # aesthetics in specific cases)
            if any(n for n in nbr_reads[0] if OPPOSITE_DIR[direction] in n["dir"] and n["pos"] != "pre_start"):
                successful_matches.append(direction)

        return successful_matches


    def _check_is_start(self, x, y, glyph):

        symbol = [l for l in self.lexicon if glyph[y][x] in l["symbol"]]

        # symbol has no reading, ignore
        if not symbol or len(symbol) == 0:
            return None

        readings = [s["readings"] for s in symbol][0]

        # symbol has no starts, ignore
        if not any(r["pos"] == "start" for r in readings):
            return None

        successful_matches = self._find_successful_matches(x, y, glyph, readings)

        if len(successful_matches) != 1:
            return None

        # the reading compatible with the direction of the strand
        reading_for_match = [r for r in readings \
            if r["pos"] == "start" \
            and r["dir"] == [successful_matches[0]]]

        if len(reading_for_match) != 1:
            raise InternalError(f"{len(reading_for_match)} dirs in a start where 1 was expected")

        return {
            "symbol": symbol[0]["symbol"],
            "name": symbol[0]["name"],
            "x": x,
            "y": y,
            "dir": successful_matches[0],
            "pos": "start",
            "type": reading_for_match[0]["type"],
            "action": None,
            "value": None,
            "vert_value": None,
            "subtype": None
        }


    def _find_strand_starts(self, glyph):
        starts = []
        for y in enumerate(glyph):
            for x in enumerate(glyph[y[0]]):
                token = self._check_is_start(x[0], y[0], glyph)
                if token:
                    starts.append(token)
        return starts


    def _interpret_strand(self, glyph, prev, start):
        """Recursively follow the data strand to determine build out its value and determine its subtype (value vs ref if data strand etc). Parameters:
            glyph: the glyph matrix
            prev: the current step's data (it will advance to the next step)
            start: the start of the strand
        This will modify the start object in place.
        """
        # At the beginning of a strand, prev is the hook which begins it (and never has any other reading).
        # We already know the direction prev is pointing, so we can look for the next character in that direction and mark as curr.
        curr = self._get_neighbor(prev["x"], prev["y"], prev["dir"], glyph, include_coords=True)

        # next_dir is the direction curr continues onto its following character
        next_dir = False

        # symbol is the metadata, pulled from the lexicon, for curr's character
        symbol = [l for l in self.lexicon if curr['symbol'] in l['symbol']]

        if not symbol or len(symbol) == 0:
            if curr['symbol'] == ' ':
                raise InternalError(f"Blank space found at {curr['x']},{curr['y']}")
            raise InternalError(f"No symbol found for {curr['symbol']}")
        if len(symbol) > 1:
            raise InternalError(f"More than one symbol found for {curr['symbol']}")

        # possible interpretations of the character
        readings = {}
        for r in [s['readings'] for s in symbol][0]:
            readings[r["pos"]] = r

        if "continue" in readings or "corner" in readings:
            # if it's for the matching direction
            if OPPOSITE_DIR[prev['dir']] in r['dir']:
                # remove entries from r['dir'] matching opposite of start['dir']
                next_dir = set(r['dir']) - set([OPPOSITE_DIR[prev['dir']]])
                if len(next_dir) != 1:
                    raise InternalError("More than one direction in next step")
                next_dir = next_dir.pop()

        # if it is moving left/right with a continue, add to value
        if "continue" in readings and next_dir:

            if not start["value"]:
                start["value"] = 0
            if not start["vert_value"]:
                start["vert_value"] = 0

            # if it's straight and left or right, we add or subtract the prime
            if next_dir == 'right':
                start['value'] += self.primes[curr["y"]]
            elif next_dir == 'left':
                start['value'] -= self.primes[curr["y"]]

            # if it's up or down, we add or subtract the prime relative to the start of this strand
            if next_dir == 'down':
                start['vert_value'] += self.primes[abs(math.floor((start["x"] - curr["x"])/2))]
            elif next_dir == 'up':
                start['vert_value'] -= self.primes[abs(math.floor((start["x"] - curr["x"])/2))]

        # TEST FOR END
        # a loc_marker is also an end, but only if it's pointing in the opposite direction of the previous character
        if "end" in readings or "loc_marker" in readings:
            if next_dir:
                # does the strand end here
                following = [i for i in self.lexicon if self._get_neighbor(curr['x'], curr['y'], next_dir, glyph) in i['symbol']]

                # there should only be one
                if following:
                    following = following[0]
                else:
                    following = None

            # if it's possible this is also a continue, we need to check if the next step has a continuation or if this is really the end
            # NOTE: We can't end on a corner or it would be a "hook" to start a strand (no strand can have a hook on both sides)
            has_connecting_sign = (next_dir and following and OPPOSITE_DIR[next_dir] in [x for xs in [r["dir"] for r in following["readings"]]for x in xs])

            if not next_dir \
                or not following \
                or not ("continue" in readings and has_connecting_sign):

                # WE ARE AT THE END of the strand
                self._mark_end(start, curr, next_dir, prev, readings)
                return

        # if it continues, load the next character
        if ("continue" in readings or "corner" in readings) and next_dir:
            curr["dir"] = next_dir
            self._interpret_strand(glyph, curr, start)
            return

        raise RivuletSyntaxError(f"No valid reading found for char {curr['x']}, {curr['y']}")


    def _mark_end(self, start, curr, next_dir, prev, readings):
        "Determine what kind of strand we have and null out anything irrelevant to its reading"

        if start["type"] == "question_marker":
            start['end_x'] = curr['x']
            start['end_y'] = curr['y']
            start['value'] = None
            start['vert_value'] = None

        # if it's a value strand, we need to mark it as such
        # check if the loc_marker reading has the right direction
        elif "loc_marker" in readings and \
            OPPOSITE_DIR[prev['dir']] in readings["loc_marker"]['dir']:

            start['value'] = None
            start['end_x'] = curr['x']
            start['end_y'] = curr['y']
            if start['type'] == "data":
                start["vert_value"] = None
                start['subtype'] = "ref"
            if start['type'] == "action":
                start["subtype"] = "list2list"
                start["command"] = self.command_map[str(start["vert_value"])]
        else:
            if start['type'] == "data":
                start['subtype'] = "value"
                start["vert_value"] = None
            if start['type'] == "action":
                start["value"] = None
                start["command"] = self.command_map[str(start["vert_value"])]
                if next_dir == "right" or next_dir == "left":
                    start['subtype'] = "list"
                else:
                    start['subtype'] = "element"


    def _lex_glyph(self, glyph):
        "Returns collection of strands with their interpretations"
        #FIXME: should ensure that starts and ends are cleared OR TAKE PARAM

        # make glyph rectangular
        glyph = [ln + [' '] * (max([len(i) for i in glyph]) - len(ln)) for ln in glyph]

        starts = self._find_strand_starts(glyph)
        for s in starts:
            self._interpret_strand(glyph, s, s)
        return starts


    def _has_continuation(self, x, y, program, dirtn):
        "Look for continuations, meant to rule out potential Starts and Ends"
        try:
            neighbor = self._get_neighbor(x, y, dirtn, program, include_coords=True)
        except IndexError:
            return False # if we are at the edge of the glyph, we can't have a continuation
        if neighbor:
            n_read = [l["readings"] for l in self.lexicon if neighbor["symbol"] in l["symbol"]]
            if n_read:
                n_read = n_read[0]
            if n_read and len([t for t in n_read if OPPOSITE_DIR[dirtn] in t["dir"]])  != 0:
                return True # has a continuation
        return False


    def _locate_glyphs(self, program):
        """Find all the Starts and Ends where:
            - everything in the col left of Start down to End is blank
            - everything in the row below End back to Start is blank
            - the Start and End are not connected to other symbols
            - the Start and End are not on the same line
          Determine level of glyph
        """
        glyph_locs = [] # return set

        starts = []
        ends = []

        for y, ln in enumerate(program):
            for x in _chars_in_list(self.get_symbol_by_name("start_glyph"), ln):
                # make sure immediate right does not also have start symbol
                if x != len(ln) - 1 and not ln[x+1] in self.get_symbol_by_name("start_glyph") and not self._has_continuation(x, y, program, "up") and not self._has_continuation(x, y, program, "down"):
                    level = 1
                    if x > 0 and ln[x-1] in self.get_symbol_by_name("start_glyph"):
                        # find the level of the glyph by walking to the left
                        for i in reversed(range(0, x)):
                            if ln[i] in self.get_symbol_by_name("start_glyph"):
                                level += 1
                            else:
                                break
                    starts.append({"y":y, "x":x, "level":level})
            for x in _chars_in_list(self.get_symbol_by_name("end_glyph"), ln):
                if not self._has_continuation(x, y, program, "down") and not self._has_continuation(x, y, program, "up"):
                    ends.append({"y":y, "x":x})

        ends_used = []
        for s in starts:
            start_matched = False
            for e in [e for e in ends if e not in ends_used]:

                if e["x"] <= s["x"] or e["y"] <= s["y"]:
                    continue

                # blank or beg of file above and not any horiz break in the middle
                if (s["y"] == 0 or all(c == ' ' for c in program[s["y"]-1])) and \
                    not any(all(c == ' ' for c in program[y]) for y in range(s["y"],e["y"])):

                    # no col to the right or all blanks to the right and no vert break in the middle
                    if (e["y"] == len(program)-1 or \
                        (all(c == ' ' for c in [arr[e["x"]+1] if len(arr) > e["x"]+1 else ' ' for arr in program[s["y"]:e["y"]]]))) and \
                        not any(all(c == ' ' for c in [arr[x] if len(arr) > x else ' ' for arr in program[s["y"]:e["y"]+1]]) for x in range(s["x"],e["x"])):

                        glyph_locs.append({"start":s,"end":e,"level":s["level"]})
                        del s["level"]
                        ends_used.append(e)
                        start_matched = True
                        break
            if not start_matched:
                raise RivuletSyntaxError(f"Start glyph at {s['x']}, {s['y']} has no matching end")
        if len(ends_used) != len(ends):
            e = min([e for e in ends if e not in ends_used])
            raise RivuletSyntaxError(f"End glyph at {e['x'], e['y']} has no corresponding Start")
        return glyph_locs


    def _load_primes(self, glyphs):
        "Load a list of primes up to the length of the longest dimension of any glyph"
        self.primes = [1]
        primes_to_count = max( \
            *[len(i['glyph']) for i in glyphs], \
            *[len(i['glyph'][0]) for i in glyphs] \
        )
        for num in range(2, primes_to_count ** 2):
            if all(num%i!=0 for i in range(2,int(math.sqrt(num))+1)):
                self.primes.append(num)
                if len(self.primes) >= primes_to_count:
                    break


    def _remove_blank_lines(self, program):
        "Clear blank lines from top and bottom of a multi-line string"
        if program[0] == [] or set(program[0]) == {' '}:
            program = program[1:]
        if program[-1] == [] or set(program[-1]) == {' '}:
            program = program[:-1]
        return program


    def _prepare_glyphs_for_lexing(self, glyph_locs, program):
        "Returns a set of individual glyphs, each with its level, with the Starts and Ends removed"
        block_tree = []
        for g in glyph_locs:
            # isolate the glyph
            glyph = [row[g["start"]["x"] - g["level"] + 1:g["end"]["x"]+1] \
                     for row in program[g["start"]["y"]:g["end"]["y"]+1]]

            # remove the start and end symbols
            for i in range(0, g["level"]):
                glyph[0][i] = ' '
            glyph[-1][-1] = ' '

            block_tree.append({"level":g["level"], "glyph":glyph})

        return block_tree


    def _parse_glyphs(self, glyphs):
        "Arrange Strands in order to be run and fill out with what they assign to, what is tested, etc"

        for glyph in glyphs:
            order = 0
            count_per_list = {}

            # primes list count = max number of lines in a glyph
            for idx in range(len(self.primes)):
                count_per_list[idx] = 0

            # build out new array in sort order
            sorted_tokens = []

            # Tokens read in X, Y order and exclude tokens that run later
            # or modify other tokens
            for token in \
                [t for t in sorted(glyph["tokens"], \
                key=lambda x: (x['x'], x['y'])) \
                    if t["type"] != "question_marker"
                    and t["type"] != "action"]:

                token["list"] = self.primes[token["y"]]
                token["order"] = order
                order += 1

                token["assign_to_cell"] = count_per_list[token["y"]]
                count_per_list[token["y"]] += 1
                sorted_tokens.append(token)

            # Question Markers are to be run last
            # read in vertical order
            for idx, token in \
                enumerate([t for t in sorted(glyph["tokens"], \
                key=lambda x: x['y']) if t["type"] == "question_marker"]):

                if idx == 0:
                    token["subtype"] = "first"
                    token["order"] = order
                    order += 1
                    sorted_tokens.append(token)
                    first_qm = token
                elif idx == 1:
                    token["subtype"] = "second"
                    if first_qm["end_x"] != token["x"] or first_qm["end_y"] != token["y"]:
                        raise RivuletSyntaxError("A second question marker must begin just below where the first ends")
                    first_qm["second"] = token
                else:
                    raise RivuletSyntaxError("Invalid number of question markers: only 0 or 2 are allowed in a glyph")

            # Ref markers determine their reference cells
            for token in [t for t in sorted_tokens if t["subtype"] == "ref"]:
                ref = [t for t in sorted_tokens if t["y"] == token["end_y"] and t["x"] < token["end_x"]]
                if not ref:
                    token["ref_cell"] = [self.primes[token["end_y"]], 0]
                else:
                    token["ref_cell"] = [self.primes[token["end_y"]], min(t["assign_to_cell"] for t in ref) + 1]

            # Action strands are added to their respective data strands
            # The top action strand for an x value goes to the top data strand for that x value
            curr_x = 0
            x_count = 0
            for actiontoken in \
                [t for t in sorted(glyph["tokens"], \
                    key=lambda x: (x['x'], x['y'])) \
                    if t["type"] == "action"]:
                if int(actiontoken["x"]) == curr_x:
                    x_count += 1
                else:
                    x_count = 0
                    curr_x = int(actiontoken["x"])
                for idx, datanode in enumerate([t for t in sorted_tokens \
                    if t["type"] == "data" and t["x"] == actiontoken["x"]]):
                    if x_count == idx:
                        datanode["action"] = actiontoken

                        # apply appropriate commnd for data token type
                        if (datanode["subtype"] == "list" or actiontoken["subtype"] == "list" or actiontoken["subtype"] == "list2list") and "list_name" in datanode["action"]["command"]:
                            datanode["action"]["command_note"] = actiontoken["command"]["list_note"]
                            datanode["action"]["command"] = actiontoken["command"]["list_name"]
                        else:
                            datanode["action"]["command_note"] = actiontoken["command"]["note"]
                            datanode["action"]["command"] = actiontoken["command"]["name"]

            glyph['tokens'] = sorted_tokens
            print(glyph["tokens"])



    def parse_program(self, program):
        "Parse a Rivulet program and return a list of commands"

        # turn into a grid
        program = [list(ln) for ln in program.splitlines()]

        program = self._remove_blank_lines(program)
        glyph_locs = self._locate_glyphs(program)

        if not glyph_locs:
            raise RivuletSyntaxError("No glyph found")

        glyphs = self._prepare_glyphs_for_lexing(glyph_locs, program)

        # now that we know the size of the largest glyph, we calculate
        # the primes for the whole program
        self._load_primes(glyphs)

        for glyph in glyphs:
            glyph["tokens"] = self._lex_glyph(glyph["glyph"])
            # if len(glyph["glyph"])
            print(glyph["tokens"])

        # re-arranges and decorates the tokens for each glyph in place
        self._parse_glyphs(glyphs)
        return glyphs
