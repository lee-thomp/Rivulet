"Interpreter for the Rivulet programming language"
from argparse import ArgumentParser
from enum import Enum
import json
import math
from riv_exceptions import RivuletSyntaxError
from riv_parser import Parser
from riv_python_transpiler import PythonTranspiler
from riv_svg_generator import SvgGenerator
from riv_themes import Themes

VERSION = "0.3"

class Interpreter:
    "Interpreter for the Rivulet programming language, main entry point"

    Action = Enum('Action', [
        ('rollback', 1),    # undo all changes to state and exit block
        ('cont', 2),        # continue to next glyph
        ('repeat', 3)       # repeat the block
    ])

    def __init__(self):
        self.outfile = None
        self.verbose = False
        self.debug = None

    def interpret_file(self, progfile, outfile, verbose, svg, theme):
        "Interpret a Rivulet program file"
        self.outfile = outfile
        self.verbose = verbose

        with open(progfile, "r", encoding="utf-8") as file:
            program = file.read()

        return self.interpret_program(program, outfile, verbose, svg, theme)
    
    def interpret_program(self, program, outfile, verbose, svg, theme):
        "Interpret a Rivulet program passed by text"
        self.verbose = verbose

        parser = Parser()

        glyphs = parser.parse_program(program)

        if svg:
            svg = SvgGenerator(Themes[theme])
            svg.generate(glyphs)

        # if self.verbose:
        #     printer = PythonTranspiler()
        #     printer.print_program(parse_tree, pseudo=True)

        return self.__interpret(glyphs)

    def __interpret(self, glyphs):
        state = dict([(1,[])])

        prime_size = 0
        prime_size = max(glyphs, key=lambda x: x["list_size"])["list_size"]

        # initialize state with lists required
        for num in range(2, prime_size ** 2):
            if all(num % i != 0 for i in range(2, int(math.sqrt(num)) + 1)):
                state[num] = []
                if len(state) >= prime_size:
                    break
        if self.verbose:
            self.debug = PythonTranspiler()

        for idx, g in enumerate(glyphs):
            g["id"] = idx

        parse_tree = self.treeify_glyphs(json.loads(json.dumps(glyphs)), 1, [])

        self.__decorate_blocks(parse_tree, 0, None)

        self.__interpret_block(parse_tree, state)


    def treeify_glyphs(self, glyphs, curr_level, tree):
        "Reorganize a flat list of glyphs into a tree by level"
        if glyphs[0]["level"] == curr_level:
            tree.append(glyphs.pop(0))
        elif glyphs[0]["level"] > curr_level:
            level = []
            tree.append(level)
            self.treeify_glyphs(glyphs, curr_level + 1, level)
        else:
            # go back up one level
            return tree

        if len(glyphs) > 0:
            self.treeify_glyphs(glyphs, curr_level, tree)

        return tree


    def __decorate_blocks(self, block, level, following = None):
        "for each glyph in a block, link to glyphs that start the block or first fall after it"
        first = None
        for idx, g in enumerate(block):

            # find first glyph for block, even if it is in a sub-block
            if idx == 0:
                first = g
                while isinstance(first, list):
                    first = first[0]

            if not isinstance(g, list):
                g["first"] = first["id"]
                g["level"] = level
                if following:
                    g["following"] = following["id"]
                else:
                    g["following"] = None
            else:
                # set following to the next glyph in the block or its first descendent
                # if there are no more, allow it to remain the existing following
                if idx < len(block) - 1:
                    f = block[idx + 1]
                    while isinstance(f, list):
                        f = f[0]
                    if not isinstance(f, list):
                        following = f
                self.__decorate_blocks(g, level + 1, following)


    def __interpret_block(self, parse_tree, state):

        rollback_state = json.loads(json.dumps(state))

        for g in parse_tree:
            if isinstance(g, list):
                self.__interpret_block(g, state)
            else:
                action = self.__interpret_glyph(g, state)
                if action == self.Action.rollback:
                    state = json.loads(json.dumps(rollback_state))
                    return # a rollback also exits the block
                if action == self.Action.cont:
                    continue
                if action == self.Action.repeat:
                    self.__interpret_block(parse_tree, state)


    def __interpret_glyph(self, glyph, state) -> Action:

        retval = self.Action.cont

        for token in glyph["tokens"]:
            if token["type"] == "question_marker":
                retval = self.__resolve_question(token, state)
            else: # is a value or a ref marker

                # if the cell is not in the list, initialize it to zero
                if 'assign_to_cell' in token and len(state[token['list']]) == token['assign_to_cell']:
                    state[token['list']].append(0)
                elif 'assign_to_cell' in token and len(state[token['list']]) < token['assign_to_cell']:
                    # shouldn't be possible
                    pass

                source = None

                list2list = not token["action"] is None and "subtype" in token["action"] and token["action"]["subtype"] == "list2list"

                # find source item
                if list2list:
                    source = state[token["ref_list"]]
                if token["subtype"] == "value":
                    source = token["value"]
                elif token["subtype"] == "ref":
                    source = state[token["ref_cell"][0]][token["ref_cell"][1]]

                # find item to apply to
                if list2list:
                    for i in range(len(state[token["list"]])):
                        state[token["list"]][i] = self.__resolve_cmd(token, state[token["list"]][i], source[i])
                elif token["action"] is None or "command" not in token["action"]:
                    # defaults to add_assign
                    state[token["list"]][token["assign_to_cell"]] += source
                elif token["action"]["command"] == "insert":
                    state[token["list"]].insert(token["assign_to_cell"], source)
                elif token["action"]["command"] == "append":
                    state[token["list"]].append(source)
                elif token["action"]["subtype"] == "list":
                    for i in range(len(state[token["list"]])):
                        state[token["list"]][i] = self.__resolve_cmd(token, state[token["list"]][i], source)
                else:
                    state[token["list"]][token["assign_to_cell"]] = self.__resolve_cmd(token, state[token["list"]][token["assign_to_cell"]], source)

        if self.verbose:
            print(self.debug.glyph_drawn(glyph["glyph"]))
            print(self.debug.glyph_pseudo(glyph))
            print(state)
            print("\n")

        return retval
    

    def __resolve_cmd(self, token, initial_value, assign_value):
        if not token["action"] or not "command" in token["action"]:
            raise RivuletSyntaxError("No command found in token")
        
        match token["action"]["command"]:
            case "addition_assignment":
                return initial_value + assign_value
            case "subtraction_assignment":
                return initial_value - assign_value
            case "overwrite":
                return assign_value
            case "multiplication_assignment":
                return initial_value * assign_value
            case "division_assignment":
                return initial_value / assign_value
            case "mod_assignment":
                return initial_value % assign_value
            case "exponent_assignment":
                return initial_value ** assign_value
            case "root_assignment":
                return initial_value ** (1 / assign_value)


    def __resolve_question(self, token, state) -> Action:
        retval = self.Action.cont

        succeeds = False

        if token["applies_to"] == "cell":
            succeeds = state[token["ref_cell"][0]][token["ref_cell"][1]] > 0
        elif token["applies_to"] == "list":
            succeeds = all(i > 0 for i in state[token["ref_list"]])
        else:
            raise RivuletSyntaxError("Could not determine what question marker applies to")

        if succeeds:
            if token["block_type"] == "while":
                retval = self.Action.repeat
        else:
            retval = self.Action.rollback

        return retval


if __name__ == "__main__":

    arg_parser = ArgumentParser(description=f'Rivulet Interpreter {VERSION}',
                            epilog='More at https://danieltemkin.com/Esolangs/Rivulet')

    arg_parser.add_argument('progfile', metavar='progfile', type=str,
                        help='Rivulet program file')
    arg_parser.add_argument('--out', dest='outfile', default=None,
                        help='where to write output from the program')
    arg_parser.add_argument('-v', dest='verbose', action='store_true',
                        default=False, help='verbose logging')
    arg_parser.add_argument('--svg', dest='svg', action='store_true', default=False,
                        help='save to svg')
    arg_parser.add_argument('--colorset', dest='color_set', default="default", help="color scheme for svg")
    args = arg_parser.parse_args()

    intr = Interpreter()
    result = intr.interpret_file(args.progfile, args.outfile, args.verbose, args.svg, args.color_set)

    if not args.outfile or args.verbose:
        print(result)
