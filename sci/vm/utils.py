# extracted from OSWorld/mm_agents
# ref: https://github.com/xlang-ai/OSWorld/blob/main/mm_agents/agent.py

import xml.etree.ElementTree as ET
from io import BytesIO
from typing import Tuple, List

import tiktoken
from PIL import Image, ImageDraw, ImageFont

attributes_ns_ubuntu = "https://accessibility.windows.example.org/ns/attributes"
attributes_ns_windows = "https://accessibility.windows.example.org/ns/attributes"
state_ns_ubuntu = "https://accessibility.ubuntu.example.org/ns/state"
state_ns_windows = "https://accessibility.windows.example.org/ns/state"
component_ns_ubuntu = "https://accessibility.ubuntu.example.org/ns/component"
component_ns_windows = "https://accessibility.windows.example.org/ns/component"
value_ns_ubuntu = "https://accessibility.ubuntu.example.org/ns/value"
value_ns_windows = "https://accessibility.windows.example.org/ns/value"
class_ns_windows = "https://accessibility.windows.example.org/ns/class"

def judge_node(node: ET, platform="ubuntu", check_image=False) -> bool:
    if platform == "ubuntu":
        _state_ns = state_ns_ubuntu
        _component_ns = component_ns_ubuntu
    elif platform == "windows":
        _state_ns = state_ns_windows
        _component_ns = component_ns_windows
    else:
        raise ValueError("Invalid platform, must be 'ubuntu' or 'windows'")

    keeps: bool = node.tag.startswith("document") \
        or node.tag.endswith("item") \
        or node.tag.endswith("button") \
        or node.tag.endswith("heading") \
        or node.tag.endswith("label") \
        or node.tag.endswith("scrollbar") \
        or node.tag.endswith("searchbox") \
        or node.tag.endswith("textbox") \
        or node.tag.endswith("link") \
        or node.tag.endswith("tabelement") \
        or node.tag.endswith("textfield") \
        or node.tag.endswith("textarea") \
        or node.tag.endswith("menu") \
        or node.tag in {
            "alert",
            "canvas",
            "check-box",
            "combo-box",
            "entry",
            "icon",
            "image",
            "paragraph",
            "scroll-bar",
            "section",
            "slider",
            "static",
            "table-cell",
            "terminal",
            "text",
            "netuiribbontab",
            "start",
            "trayclockwclass",
            "traydummysearchcontrol",
            "uiimage",
            "uiproperty",
            "uiribboncommandbar"
        }

    keeps = keeps and (
            platform == "ubuntu"
                and node.get("{{{:}}}showing".format(_state_ns), "false") == "true"
                and node.get("{{{:}}}visible".format(_state_ns), "false") == "true"
                or platform == "windows"
                and node.get("{{{:}}}visible".format(_state_ns), "false") == "true"
        ) and (
            node.get("{{{:}}}enabled".format(_state_ns), "false") == "true"
                or node.get("{{{:}}}editable".format(_state_ns), "false") == "true"
                or node.get("{{{:}}}expandable".format(_state_ns), "false") == "true"
                or node.get("{{{:}}}checkable".format(_state_ns), "false") == "true"
        ) and (
            node.get("name", "") != "" or node.text is not None and len(node.text) > 0 \
                or check_image
                and node.get("image", "false") == "true"
        )

    coordinates: Tuple[int, int] = eval(node.get("{{{:}}}screencoord".format(_component_ns), "(-1, -1)"))
    sizes: Tuple[int, int] = eval(node.get("{{{:}}}size".format(_component_ns), "(-1, -1)"))
    keeps = keeps and coordinates[0] >= 0 and coordinates[1] >= 0 and sizes[0] > 0 and sizes[1] > 0
    return keeps

def filter_nodes(root: ET, platform: str ="ubuntu", check_image: bool = False) -> List:
    filtered_nodes = []
    for node in root.iter():
        if judge_node(node, platform, check_image):
            filtered_nodes.append(node)
    return filtered_nodes

def draw_bounding_boxes(nodes: List, image_file_content: bytes, down_sampling_ratio=1.0, platform="ubuntu"):
    if platform == "ubuntu":
        _state_ns = state_ns_ubuntu
        _component_ns = component_ns_ubuntu
        _value_ns = value_ns_ubuntu
    elif platform == "windows":
        _state_ns = state_ns_windows
        _component_ns = component_ns_windows
        _value_ns = value_ns_windows
    else:
        raise ValueError("Invalid platform, must be 'ubuntu' or 'windows'")

    image_stream = BytesIO(image_file_content)
    image = Image.open(image_stream)
    if float(down_sampling_ratio) != 1.0:
        image = image.resize((int(image.size[0] * down_sampling_ratio), int(image.size[1] * down_sampling_ratio)))
    draw = ImageDraw.Draw(image)
    marks = []
    drew_nodes = []
    text_informations: List[str] = ["index\ttag\tname\ttext"]

    try:
        font = ImageFont.truetype("arial.ttf", 15)
    except IOError:
        font = ImageFont.load_default()

    index = 1

    for _node in nodes:
        coords_str = _node.attrib.get('{{{:}}}screencoord'.format(_component_ns))
        size_str = _node.attrib.get('{{{:}}}size'.format(_component_ns))

        if coords_str and size_str:
            try:
                coords = tuple(map(int, coords_str.strip('()').split(', ')))
                size = tuple(map(int, size_str.strip('()').split(', ')))

                import copy
                original_coords = copy.deepcopy(coords)
                original_size = copy.deepcopy(size)

                if float(down_sampling_ratio) != 1.0:
                    coords = tuple(int(coord * down_sampling_ratio) for coord in coords)
                    size = tuple(int(s * down_sampling_ratio) for s in size)

                if size[0] <= 0 or size[1] <= 0:
                    raise ValueError(f"Size must be positive, got: {size}")

                bottom_right = (coords[0] + size[0], coords[1] + size[1])

                if bottom_right[0] < coords[0] or bottom_right[1] < coords[1]:
                    raise ValueError(f"Invalid coordinates or size, coords: {coords}, size: {size}")

                cropped_image = image.crop((*coords, *bottom_right))
                if len(set(list(cropped_image.getdata()))) == 1:
                    continue

                draw.rectangle([coords, bottom_right], outline="red", width=1)

                text_position = (coords[0], bottom_right[1])
                text_bbox: Tuple[int, int, int, int] = draw.textbbox(text_position, str(index), font=font, anchor="lb")

                draw.rectangle(text_bbox, fill='black')
                draw.text(text_position, str(index), font=font, anchor="lb", fill="white")

                marks.append([original_coords[0], original_coords[1], original_size[0], original_size[1]])
                drew_nodes.append(_node)

                if _node.text:
                    node_text = (_node.text if '"' not in _node.text \
                                     else '"{:}"'.format(_node.text.replace('"', '""'))
                                 )
                elif _node.get("{{{:}}}class".format(class_ns_windows), "").endswith("EditWrapper") \
                        and _node.get("{{{:}}}value".format(_value_ns)):
                    node_text = _node.get("{{{:}}}value".format(_value_ns), "")
                    node_text = (node_text if '"' not in node_text \
                                     else '"{:}"'.format(node_text.replace('"', '""'))
                                 )
                else:
                    node_text = '""'
                text_information: str = "{:d}\t{:}\t{:}\t{:}".format(index, _node.tag, _node.get("name", ""), node_text)
                text_informations.append(text_information)

                index += 1

            except ValueError:
                pass

    output_image_stream = BytesIO()
    image.save(output_image_stream, format='PNG')
    image_content = output_image_stream.getvalue()

    return marks, drew_nodes, "\n".join(text_informations), image_content

def linearize(a11y_tree: str, platform: str = "ubuntu"):
    if platform == "ubuntu":
        _attributes_ns = attributes_ns_ubuntu
        _state_ns = state_ns_ubuntu
        _component_ns = component_ns_ubuntu
        _value_ns = value_ns_ubuntu
    elif platform == "windows":
        _attributes_ns = attributes_ns_windows
        _state_ns = state_ns_windows
        _component_ns = component_ns_windows
        _value_ns = value_ns_windows
    else:
        raise ValueError("Invalid platform, must be 'ubuntu' or 'windows'")

    filtered_nodes = filter_nodes(ET.fromstring(a11y_tree), platform)
    linearized_a11y_tree = ["tag\tname\ttext\tclass\tdescription\tposition (top-left x&y)\tsize (w&h)"]

    for node in filtered_nodes:
        if node.text:
            text = (node.text if '"' not in node.text else '"{:}"'.format(node.text.replace('"', '""')))
        elif node.get("{{{:}}}class".format(class_ns_windows), "").endswith("EditWrapper") \
                and node.get("{{{:}}}value".format(_value_ns)):
            node_text = node.get("{{{:}}}value".format(_value_ns), "")
            text = (node_text if '"' not in node_text else '"{:}"'.format(node_text.replace('"', '""')))
        else:
            text = '""'

        linearized_a11y_tree.append("{:}\t{:}\t{:}\t{:}\t{:}\t{:}\t{:}".format(
            node.tag, node.get("name", ""),
            text,
            node.get("{{{:}}}class".format(_attributes_ns), "") if platform == "ubuntu" else node.get("{{{:}}}class".format(class_ns_windows), ""),
            node.get("{{{:}}}description".format(_attributes_ns), ""),
            node.get('{{{:}}}screencoord'.format(_component_ns), ""),
            node.get('{{{:}}}size'.format(_component_ns), "")
        ))

    return "\n".join(linearized_a11y_tree)

def trim(linearized_a11y_tree, max_tokens):
    enc = tiktoken.encoding_for_model("gpt-4")
    tokens = enc.encode(linearized_a11y_tree)
    if len(tokens) > max_tokens:
        linearized_a11y_tree = enc.decode(tokens[:max_tokens])
        linearized_a11y_tree += "[...]\n"
    return linearized_a11y_tree

def tag_screenshot(screenshot: bytes, a11y_tree: str, platform: str = "ubuntu"):
    nodes = filter_nodes(ET.fromstring(a11y_tree), platform=platform, check_image=True)
    marks, drew_nodes, element_list, tagged_screenshot = draw_bounding_boxes(nodes, screenshot)
    return marks, drew_nodes, tagged_screenshot, element_list
