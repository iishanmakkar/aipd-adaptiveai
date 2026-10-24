// AdaptiveAI task runner: the loop that turns a goal into verified steps.
//
// Deliberately free of any network call. `nextStep` is injected, so the same loop
// that will one day ask the backend what to do next can be driven in tests by a
// scripted plan - and the control flow that actually matters for safety (stop when
// a step fails, pause at the gate, never exceed the budget) is the part under test
// here, not the model's prose.
//
// The three properties this file exists to guarantee:
//   1. a failed step halts the run - pressing on to a payment after the seat
//      selection silently failed is precisely the harm being prevented;
//   2. a gated action cannot proceed without an explicit confirmation from the
//      host (which will come from the user's voice, never from the planner);
//   3. every step records its outcome, so a run can be reviewed afterwards rather
//      than remembered as "it seemed to work".
(function (global) {
  'use strict';

  var DEFAULT_MAX_STEPS = 12;

  function isPass(status) {
    return status === 'verified' || status === 'pressed' || status === 'not_selected';
  }

  async function run(options) {
    var opts = options || {};
    var goal = opts.goal || '';
    var nextStep = opts.nextStep;
    var send = opts.send;
    var confirm = opts.confirm || function () { return Promise.resolve(false); };
    var narrate = opts.narrate || function () {};
    var maxSteps = opts.maxSteps || DEFAULT_MAX_STEPS;
    var spendCeiling = opts.spendCeiling;

    if (typeof nextStep !== 'function' || typeof send !== 'function') {
      throw new Error('runner needs nextStep and send');
    }

    var steps = [];
    var spoken = [];
    var lastOutcome = null;
    var status = 'completed';
    var plannerFinished = false;

    function say(text) {
      if (!text) return;
      spoken.push(text);
      try { narrate(text); } catch (e) { /* a broken speaker must not abort a run */ }
    }

    for (var index = 0; index < maxSteps; index++) {
      var context = {
        goal: goal,
        stepCount: steps.length,
        lastOutcome: lastOutcome,
        // Awaited: a page read that has to cross a message port is the normal
        // case, and handing the planner a Promise instead of a snapshot would
        // look like an empty page - which it would then honestly report as one.
        snapshot: opts.snapshot ? await opts.snapshot() : null,
        availableLabels: opts.availableLabels ? await opts.availableLabels() : [],
      };
      var step = await nextStep(context);
      if (!step) { status = 'completed'; plannerFinished = true; break; }

      // A reply that is not an action: the planner finished, needs something from
      // the user, or gave up. The runner speaks what the planner said instead of
      // rewording a refusal into something that sounds like a result, and each
      // case gets its own run status so a review can tell them apart.
      if (step.control) {
        say(step.say);
        steps.push({ description: step.say || null, action: null,
                     status: 'planner_' + step.control, reason: step.why || null });
        if (step.control === 'done') { status = 'completed'; plannerFinished = true; }
        else if (step.control === 'ask') { status = 'needs_user'; }
        else { status = 'stopped'; }
        break;
      }

      if (!step.action || !step.ref) {
        status = 'stopped';
        say('I could not work out what to do next, so I stopped.');
        steps.push({ description: step.description || null, status: 'invalid_step' });
        break;
      }

      var outcome = await send({
        action: step.action, ref: step.ref, value: step.value,
        expect: step.expect, description: step.description,
        spendCeiling: spendCeiling,
      });

      var record = {
        description: step.description || (step.action + ' ' + step.ref),
        action: step.action,
        status: outcome && outcome.status ? outcome.status : 'failed',
        readback: outcome ? outcome.readback : null,
        reason: outcome ? outcome.reason : 'no outcome returned',
      };
      steps.push(record);
      lastOutcome = outcome;

      if (record.status === 'gated') {
        var verdict = outcome.gate || {};
        var amount = verdict.amount ? verdict.amount.text : null;
        say('About to ' + (step.description || record.action) +
            (amount ? ' for ' + amount : '') + '. ' +
            (verdict.reason ? 'This ' + verdict.reason + '. ' : '') +
            'Say yes to go ahead, or no to stop.');
        var allowed = false;
        try {
          allowed = !!(await confirm(record, verdict));
        } catch (e) {
          allowed = false;   // a failing confirmation channel must not approve
        }
        if (!allowed) {
          status = 'cancelled';
          say('Okay, nothing was pressed.');
          break;
        }
        // Re-send with the human's approval; the gate in the content script still
        // decides, so this can only unlock what the local rule already flagged.
        var approved = await send({
          action: step.action, ref: step.ref, value: step.value,
          expect: step.expect, description: step.description,
          confirm: true,
          confirmStrong: !!verdict.exceedsCeiling,
        });
        record.status = approved && approved.status ? approved.status : 'failed';
        record.readback = approved ? approved.readback : record.readback;
        record.reason = approved ? approved.reason : record.reason;
        record.confirmedByUser = true;
        // The outcome the planner will be shown is the one the page actually
        // returned, not the pre-approval "gated": recorded as gated, the next
        // history line told the model the press never happened when it did.
        lastOutcome = approved || outcome;
        if (record.status !== 'verified' && record.status !== 'pressed') {
          status = 'failed';
          say('I did that and it did not work: ' + (record.reason || 'no reason given'));
          break;
        }
        continue;
      }

      if (!isPass(record.status)) {
        status = 'failed';
        say('I could not ' + (step.description || record.action) + ': ' +
            (record.reason || 'it did not work') + '. I have stopped here.');
        break;
      }

      if (step.say) say(step.say);
    }

    // The planner never said it was done and the loop ran out: report that as a
    // budget stop rather than dressing it up as completion.
    if (status === 'completed' && !plannerFinished) {
      status = 'budget';
      say('I reached my limit of ' + maxSteps + ' steps without finishing. ' +
          'Nothing was rushed to make the answer fit.');
    }

    return {
      goal: goal,
      status: status,
      steps: steps,
      narration: spoken,
      stepsVerified: steps.filter(function (s) {
        return s.status === 'verified' || s.status === 'pressed';
      }).length,
    };
  }

  var AdaptiveAIRunner = { run: run, isPass: isPass, DEFAULT_MAX_STEPS: DEFAULT_MAX_STEPS };
  global.AdaptiveAIRunner = AdaptiveAIRunner;
  if (typeof module !== 'undefined' && module.exports) module.exports = AdaptiveAIRunner;
})(typeof window !== 'undefined' ? window : globalThis);
