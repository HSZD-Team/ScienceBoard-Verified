import sys
import re

from typing import List, Tuple, Dict
from typing import Optional, Any, Self
from dataclasses import dataclass

sys.dont_write_bytecode = True
from .manager import OBS, Manager
from .log import VirtualLog
from .agent import Agent, AIOAgent
from .agent import PlannerAgent, GrounderAgent
from .agent import CoderAgent, ActorAgent
from .prompt import TypeSort, CodeLike


@dataclass
class Community:
    def __post_init__(self):
        self.vlog = VirtualLog()

    @property
    def agents(self) -> List[Tuple[str, Agent]]:
        return [
            (key, getattr(self, key))
            for key in self.__dataclass_fields__.keys()
            if isinstance(getattr(self, key), Agent)
        ]

    def __iter__(self) -> Self:
        self.iter_pointer = 0
        return self

    def __next__(self):
        if self.iter_pointer < len(self.agents):
            self.iter_pointer += 1
            return self.agents[self.iter_pointer - 1]
        else:
            raise StopIteration

    def __call__(
        self,
        steps: Tuple[int, int],
        inst: str,
        obs: Dict[str, Any],
        code_info: tuple[set[str], Optional[List[List[int]]]],
        type_sort: TypeSort,
        timeout: int,
        manager: Manager
    ) -> List[CodeLike]:
        raise NotImplementedError


@dataclass
class AllInOne(Community):
    mono: AIOAgent

    def __call__(
        self,
        steps: Tuple[int, int],
        inst: str,
        obs: Dict[str, Any],
        code_info: tuple[set[str], Optional[List[List[int]]]],
        type_sort: TypeSort,
        timeout: int,
        manager: Manager
    ) -> List[CodeLike]:
        step_index, total_steps = steps
        init_kwargs = {
            "inst": inst,
            "type_sort": type_sort,
            "primitives": code_info[0],
            "manager": manager
        } if step_index == 0 else None

        user_content = self.mono._step(obs, init_kwargs)
        response_message = self.mono(user_content, timeout=timeout)

        assert len(response_message.content) == 1
        response_content = response_message.content[0]

        self.vlog.info(
            f"Response {step_index + 1}/{total_steps}: \n" \
                + str(response_content.text)
        )
        return self.mono.code_handler(response_content, *code_info)


@dataclass
class SeeAct(Community):
    planner: PlannerAgent
    grounder: GrounderAgent

    def __call__(
        self,
        steps: Tuple[int, int],
        inst: str,
        obs: Dict[str, Any],
        code_info: tuple[set[str], Optional[List[List[int]]]],
        type_sort: TypeSort,
        timeout: int,
        manager: Manager
    ) -> List[CodeLike]:
        step_index, total_steps = steps
        first_step = step_index == 0

        init_kwargs = {
            "inst": inst,
            "type_sort": type_sort,
            "primitives": code_info[0],
            "manager": manager
        } if first_step else None

        planner_content = self.planner._step(obs, init_kwargs)
        planner_reponse_message = self.planner(planner_content, timeout=timeout)

        assert len(planner_reponse_message.content) == 1
        planner_response_content = planner_reponse_message.content[0]

        self.vlog.info(
            f"Response of planner {step_index + 1}/{total_steps}: \n" \
                + planner_response_content.text
        )

        codes = self.planner.code_handler(planner_response_content, *code_info)

        if first_step:
            self.grounder._init(obs.keys(), **init_kwargs)

        # to intercept special codes
        if codes[0].desc is False:
            return codes

        obs[OBS.schedule] = codes[0].code
        grounder_content = self.grounder._step(obs)
        grounder_response_message = self.grounder(grounder_content, timeout=timeout)

        assert len(grounder_response_message.content) == 1
        grounder_response_content = grounder_response_message.content[0]

        self.vlog.info(
            f"Response of grounder {step_index + 1}/{total_steps}: \n" \
                + grounder_response_content.text
        )
        return self.grounder.code_handler(grounder_response_content, *code_info)


@dataclass
class Disentangled(Community):
    coder: CoderAgent
    actor: ActorAgent

    def __call__(
        self,
        steps: Tuple[int, int],
        inst: str,
        obs: Dict[str, Any],
        code_info: tuple[set[str], Optional[List[List[int]]]],
        type_sort: TypeSort,
        timeout: int,
        manager: Manager
    ) -> List[CodeLike]:
        step_index, total_steps = steps
        first_step = step_index == 0

        init_kwargs = {
            "inst": inst,
            "type_sort": type_sort,
            "primitives": code_info[0],
            "manager": manager
        } if first_step else None

        coder_content = self.coder._step(obs, init_kwargs)
        coder_reponse_message = self.coder(coder_content, timeout=timeout)

        assert len(coder_reponse_message.content) == 1
        coder_response_content = coder_reponse_message.content[0]

        self.vlog.info(
            f"Response of coder {step_index + 1}/{total_steps}: \n" \
                + coder_response_content.text
        )

        codes = self.coder.code_handler(coder_response_content, *code_info)

        # a dummy system_message is required for actor._step()
        if first_step:
            self.actor._init(obs.keys(), **init_kwargs)

        pattern = r'# *(.+)\n *' + re.escape(CoderAgent.PLACEHOLDER)
        has_placeholder = lambda code: CoderAgent.PLACEHOLDER in code
        has_comment = lambda code: re.search(pattern, code) is not None

        # intercept if no placeholders found
        if all([not has_placeholder(code.code) for code in codes]):
            return codes

        # skip if some placeholders has no comments
        # 
        if not all([
            not has_placeholder(code.code) or has_comment(code.code)
            for code in codes
        ]):
            self.vlog.info(f"Unmarked placeholders found; skip this step.")
            return []

        results = []
        for code in codes:
            code_str = code.code
            if not has_placeholder(code_str):
                results.append(code)
                continue

            match_obj = re.search(pattern, code_str)
            obs[OBS.cloze] = match_obj[1]
            actor_content = self.actor._step(obs)
            actor_response_message = self.actor(actor_content, timeout=timeout)

            assert len(actor_response_message.content) == 1
            actor_response_content = actor_response_message.content[0]

            self.vlog.info(
                f"Response of actor {step_index + 1}/{total_steps}: \n" \
                    + actor_response_content.text
            )

            if len(prev:=code_str[:match_obj.span()[0]]) > 0:
                results.append(CodeLike(code=prev))

            results.append(self.actor.code_handler(
                actor_response_content,
                *code_info
            )[0])

            if len(post:=code_str[match_obj.span()[1]:]) > 0:
                results.append(CodeLike(code=post))

        return results
