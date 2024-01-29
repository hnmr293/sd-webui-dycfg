import gradio as gr

from modules.processing import StableDiffusionProcessing
from modules import scripts
from modules.sd_samplers_cfg_denoiser import CFGDenoiser
from scripts.dycfg_xyz import init_xyz


NAME = "DyCFG"

ORIGINAL = "combine_denoised"
SAVED = f"_{NAME}_original_{ORIGINAL}"
DENOISER_CLASS = CFGDenoiser


def to_f(v):
    return float(v)


def to_i(v):
    return int(float(v))


class Script(scripts.Script):
    def title(self):
        return NAME

    def show(self, is_img2img):
        return scripts.AlwaysVisible

    def ui(self, is_img2img):
        with gr.Group():
            with gr.Accordion(NAME, open=False):
                enabled = gr.Checkbox(label="Enabled", value=False)

                elems = []
                for _ in range(3):
                    with gr.Row():
                        start = gr.Number(
                            value=0,
                            label="Start",
                            precision=0,
                            minimum=0,
                            maximum=500,
                            step=1,
                            elem_classes=[f'{NAME}_number'],
                        )
                        end = gr.Number(
                            value=0,
                            label="End (inclusive)",
                            precision=0,
                            minimum=0,
                            maximum=500,
                            step=1,
                            elem_classes=[f'{NAME}_number'],
                        )
                        value = gr.Number(
                            value=7.0,
                            label="CFG scale",
                            precision=2,
                            minimum=1.0,
                            maximum=100.0,
                            step=0.01,
                            elem_classes=[f'{NAME}_number'],
                        )
                        intp = gr.Radio(
                            choices=["Default", "Linear", "Fixed"],
                            value="Default",
                            label="Interpolation",
                        )
                    elems.extend([start, end, value, intp])

        return [
            enabled,
            *elems,
        ]

    def process(
        self,
        p: StableDiffusionProcessing,
        enabled: bool,
        *elems,
    ):
        original, _ = self.unhook(DENOISER_CLASS)

        if not enabled:
            return

        scales = ["Default" for _ in range(p.steps)]

        elems = [elems[i : i + 4] for i in range(0, len(elems), 4)]
        for start, end, value, intp in elems:
            start = to_i(start)
            end = to_i(end)
            value = to_f(value)

            if start == 0 and end == 0:
                continue

            start = max(1, start)

            if end <= 0:
                end = p.steps
            if end < start:
                continue

            value = max(1, value)

            for i in range(start - 1, end):
                # start-1 .. end-1
                scales[i] = value
            for i in range(start - 2, -1, -1):
                if isinstance(scales[i], str):
                    scales[i] = intp
                else:
                    break

        scales = ["Default", *scales, "Default"]  # add sentinels

        # scales = [ Default 7 7 7 Default 9 9 9 9 Fixed Fixed 4 4 Linear Linear Linear 3 3 3 Linear Linear Linear Default ]
        # while any(isinstance(x, str) for x in scales):
        prev = p.cfg_scale
        for i in range(len(scales)):
            if scales[i] == "Default":
                scales[i] = p.cfg_scale
                # scales = [ * 7 7 7 * 9 9 9 9 Fixed Fixed 4 4 Linear Linear Linear 3 3 3 Linear Linear Linear * ]
            elif scales[i] == "Fixed":
                assert not isinstance(prev, str), f"prev = {prev}"
                scales[i] = prev
                # scales = [ * 7 7 7 * 9 9 9 9 < < 4 4 Linear Linear Linear 3 3 3 Linear Linear Linear * ]
            prev = scales[i]

        for i in range(len(scales)):
            if scales[i] == "Linear":
                assert i != 0 and i != len(scales) - 1, f"i = {i}"
                prev = scales[i - 1]
                assert not isinstance(prev, str)
                for j in range(i + 1, len(scales)):
                    if scales[j] != "Linear":
                        break
                # scales = [ * 7 7 7 * 9 9 9 9 < < 4 4 Linear Linear Linear 3 3 3 Linear Linear Linear * ]
                #                                    p i                    j   p i                    j
                assert j != len(scales) - 1, f"j = {j}"
                next = scales[j]
                assert not isinstance(next, str), f"next = {next}"
                distance = j - i + 1
                d = (next - prev) / distance
                for k in range(i, j):
                    scales[k] = prev + (k - i + 1) * d

        # scales = [ * 7 7 7 * 9 9 9 9 < < 4 4 ~ ~ ~ 3 3 3 ~ ~ ~ * ]

        scales = scales[1:-1]
        assert len(scales) == p.steps, f"scales = {scales}"

        print(f"[{NAME}] scales =", scales)

        assert not any(isinstance(x, str) for x in scales), f"scales = {scales}"

        def do_cfg(self, x_out, conds_list, uncond, cond_scale, *args, **kwargs):
            #print(f"\nstep = {self.step}, scale = {scales[self.step]}\n")
            return original(self, x_out, conds_list, uncond, scales[self.step], *args, **kwargs)

        self.hook(DENOISER_CLASS, do_cfg)

        p.extra_generation_params.update(
            {
                f"{NAME} enabled": enabled,
                **{f"{NAME} {i}": elem for i, elem in enumerate(elems)},
            }
        )

        print(f"[{NAME}] enabled")

        return

    def postprocess(self, p, processed, enabled, *args):
        # may not be called
        if enabled:
            self.unhook(DENOISER_CLASS)

    def unhook(self, denoiser_cls):
        current = getattr(denoiser_cls, ORIGINAL)
        original = getattr(denoiser_cls, SAVED, current)
        if hasattr(denoiser_cls, SAVED):
            delattr(denoiser_cls, SAVED)
        setattr(denoiser_cls, ORIGINAL, original)
        return original, current

    def hook(self, denoiser_cls, fn):
        original, _ = self.unhook(denoiser_cls)
        setattr(denoiser_cls, SAVED, original)
        setattr(denoiser_cls, ORIGINAL, fn)

init_xyz(NAME, Script)
