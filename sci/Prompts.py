VM_USERNAME = "user"
VM_PASSWORD = "password"

# naming criteria: `{TYPE_SORT}_{FIELD}`, take `TYPE_SORT=LEAN_RAW, FIELD=TIPS` for example
# - `TYPE_SORT`: fall back to `LEAN_XXX` if `LEAN_RAW_XXX` does not exist; fall back to default value if `LEAN_XXX` does not exists
# - `FIELD`: act as a padding for reserved slots in AIOPromptFactory
#    - `IS`: str, a breif introduction of what this application is
#    - `NEED`: str, a generalization of demanded input
#    - `USAGE`: List[str], multiple lines of interaction rules to be explained to models
#    - `TIPS`: List[str], multiple lines of additional tips needing extra attention

LEAN_IS = "an interactive theorem prover"
LEAN_RAW_NEED = "JSON of Lean REPL"
LEAN_RAW_USAGE = [
    "You will be given an unproved theorem declared by `sorry`, which is what you need to prove.",
    "Each round you will receive the imports information and initial states together with possible historical interaction records as textual observation, and you are expected to apply EXACTLY ONE tactic as a response.",
    "Your submission will be passed to REPL directly, and it should be a JSON with and only with `tactic` and `proofState` fields, such as {\"tactic\": \"apply Int.natAbs\", \"proofState\": 0}`.",
    "It is worth noting that the `proofState` which REPL returns contains all proof states stored, so your JSON should also contains this field from which the proof continues."
]
LEAN_RAW_TIPS = [
    "DO NOT use `sorry` or `admit` to close the proof forcibly, or your input will be ignored.",
    "NEVER submit any Lean 3 code which the compiler of Lean 4 no longer accepts."
]
LEAN_VM_TIPS = [
    "DO NOT modify anything above the line containing `sorry`.",
    "DO NOT use `sorry` or `admit` to close the proof forcibly, or your input will be ignored.",
    "DO NOT write lean code in code blocks directly in your response; use `pyautogui` of Python instead.",
    "NEVER submit any Lean 3 code which the compiler of Lean 4 no longer accepts."
]

CHIMERAX_IS = "a molecular visualization software"
CHIMERAX_VM_TIPS = [
    "DO NOT introduce any unrelated models or easily close existing models, otherwise the task might be evaluated as FAILED.",
    "DO NOT close the current ChimeraX session, or every effort you made will be in vain.",
    "NEVER try to reopen the command line interface in ChimeraX if it is hidden, because it has been deactivated and cannot do anything. But you are welcome to use it once it is presented."
]

KALGEBRA_IS = "a mathematical graph calculator"
KALGEBRA_VM_TIPS = [
    "DO NOT plot any of parametric equations in 2D Graph.",
    "Be aware that equations in plotting is a bit different from notations of real mathematics."
]

CELESTIA_IS = "a three-dimension space simulator"
CELESTIA_VM_TIPS = [
    "The criterion for a celestial body to be displayed on the screen is that the object's center is within the window range and is not blocked by others."
]

GRASSGIS_IS = "a GIS software suite used for geospatial data management and analysis, etc."
GRASSGIS_VM_TIPS = [
    "DO NOT switch to multi-window mode.",
    "DO NOT toggle more than one map display in map panel; just use 'Map Display 1'."
]

TEXSTUDIO_IS = "an integrated writing environment for creating LaTeX documents"
LEAN_VM_USAGE = [
    "You are given a LaTeX project opened in TeXstudio filled with some text, and possibly some lipsums.",
    "What should be done is to make some minor changes to the documents based on the information obtained from possibly existed meaningful text, other scientific applications or Internet, which depends on concrete problems, while making sure that the project can be compiled successfully."
]
TEXSTUDIO_VM_TIPS = [
    "Don't forget to save after you make some editions to the text.",
    "NEVER change irrelevant text because your answer will be executed an exact match between the unique answer after you finish the task.",
    "The sequence of compilation is pdflatex (-> bibtex -> pdflatex -> pdflatex if .bib exists), so warnings or errors inside the TeXstudio do not necessarily lead to compiling fail."
]
