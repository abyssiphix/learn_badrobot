Official Code as Policies LMP adaptation for the current normal-task baseline

Upload these files beside your existing cap_env.py in:
  /root/autodl-tmp/cap-adapt

Use your existing cap-official-env environment. Install requirements-lmp.txt,
then run:
  python prepare_cap_lmp.py --notebook /root/autodl-tmp/cap-official/code_as_policies/Interactive_Demo.ipynb
  python run_cap_lmp.py

The runner prompts for a DeepSeek API key without echoing it. It can also read
DEEPSEEK_API_KEY. Do not place keys in source files or share them in chat.
Default model: deepseek-flash, non-thinking mode. Maximum 12 API calls, 60-second
timeout per request, 600-second total timeout. No automatic API retries.

Outputs: outputs/lmp_TIMESTAMP/{api_calls/,execution.log,result.json,before.png,
after.png,pick_place.mp4}. A run can use several LMP API calls. Video is exported
when frames exist, including after many failures. The current evaluator checks
only the task 'red block on yellow bowl', regardless of the instruction string.

Extraction requires commit 3ef52111c1fabc301880818f5a547570e926a76b. Official
classes, wrapper, six few-shot prompt strings and config are extracted from
the notebook. Original cells and lmp_manifest.json are preserved. Necessary
changes: legacy Completion calls are bridged to chat completions with an added
continuation-only system instruction; engine is selected at runtime; API
errors fail fast; legacy Edit is disabled. Complete outer Markdown fences are
removed, while both raw and cleaned responses are logged. Existing environment
adaptations (TinyRenderer and self.render_image) remain in effect. Physics
timestep is explicitly set to the environment's declared dt after reset.

This changes the model, API format and renderer. It is a normal-task integration
check, not a reproduction of the numerical BadRobot results. The original
exec_safe function executes generated Python and is NOT a security sandbox.
Run this stage with normal simulation tasks, not arbitrary unreviewed code.

Validation performed locally: extraction from pinned source; unchanged prompt
values; nested LMP dispatch and recursive function generation using mocked
model responses and mocked geometry/dependency modules; action coordinate
dispatch; API logging and failure cases. No real API call or PyBullet run was
performed locally. Full dependency/API/physics validation is on AutoDL.
