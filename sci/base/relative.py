import inspect

ORIGINAL = {}
ABSOLUTE = False

def switch(func_name, xRange=(0, 1), yRange=(0, 1), pos=(0, 1), offset=False):
    global ORIGINAL, ABSOLUTE
    ORIGINAL[func_name] = getattr(__import__("pyautogui"), func_name)

    def new_func(*args, **kwargs):
        global ORIGINAL
        if hasattr(__import__("pyautogui"), inspect.stack()[1].function):
            ORIGINAL[func_name](*args, **kwargs)
            return

        xStr, yStr = "x", "y"
        xRel, yRel = 0, 0
        screenWidth, screenHeight = __import__("pyautogui").size()

        if offset:
            xStr += "Offset"
            yStr += "Offset"

        if xStr in kwargs and yStr in kwargs:
            xRel, yRel = kwargs[xStr], kwargs[yStr]
            del kwargs[xStr], kwargs[yStr]
        else:
            xRel, yRel = args[pos[0]], args[pos[1]]
            args = [item for index, item in enumerate(args) if index not in pos]

        xAbs, yAbs = (
            (xRel - xRange[0]) / xRange[1] * screenWidth,
            (yRel - yRange[0]) / yRange[1] * screenHeight
        )
        ORIGINAL[func_name](xAbs, yAbs, *args, **kwargs)

    setattr(__import__("pyautogui"), func_name, new_func)

switch("moveTo")
switch("moveRel", offset=True)
switch("dragTo")
switch("dragRel", offset=True)
switch("click")
switch("rightClick")
switch("middleClick")
switch("doubleClick")
switch("tripleClick")
switch("mouseDown")
switch("mouseUp")
