# Future Research Directions (Not Yet Implemented)

## Grouping Strategy Optimization

The current system uses **random selection** for matchup generation. This provides a solid baseline, but there are several areas for potential improvement:

### Investigation Areas

1. **Similar-Skill Grouping (delta_mu)**
   - **Hypothesis**: Grouping crashes with similar skill levels (μ values) may produce more informative comparisons
   - **Current Implementation**: Uses random selection for all matchups
   - **Proposed Change**: Add `delta_mu` parameter to group crashes within score threshold (|μ₁ - μ₂| ≤ delta_mu)
   - **Metrics**: Compare convergence speed and ranking quality vs random grouping
   - **Rationale for current approach**: Random grouping is simpler and provides good exploration; unclear if nearby-μ grouping provides significant benefits

2. **Uncertainty-Based Grouping**
   - **Hypothesis**: Grouping high-uncertainty crashes together may be more informative than mixing with random crashes
   - **Implementation**: Select groups of highest-σ crashes for direct uncertainty resolution
   - **Metrics**: Measure uncertainty reduction per evaluation

3. **Adaptive Grouping Strategies**
   - **Hypothesis**: Different grouping strategies may be optimal at different tournament phases
   - **Implementation**: Use random grouping early, uncertainty-based grouping late
   - **Metrics**: Track convergence curves for different strategies

4. **Balanced Grouping**
   - **Hypothesis**: Mixing high-uncertainty with medium-uncertainty crashes may provide better information gain
   - **Implementation**: Weighted selection combining uncertainty and diversity
   - **Metrics**: Information-theoretic measures of comparison value

### Research Methodology

To investigate these approaches:

1. **A/B Testing**: Run tournaments with different grouping strategies on identical crash sets
2. **Convergence Analysis**: Measure ranking quality vs evaluation count
3. **Information Gain**: Quantify the informativeness of different comparison types
4. **Statistical Significance**: Use proper statistical tests to validate improvements

### Implementation Strategy

- **Experimental Branch**: Implement new strategies in feature branches
- **Metrics Collection**: Add detailed logging of grouping decisions and outcomes
- **Benchmarking**: Use standardized crash sets for consistent comparison
- **Gradual Rollout**: Test on small tournaments before large-scale deployment

**Note**: Any new grouping strategies should demonstrate statistically significant improvements in convergence speed or ranking quality before being merged to master.

## Uncertainty-Based Stopping Conditions

Currently, tournaments run until budget is exhausted. An alternative approach would be to stop when uncertainty converges below a threshold.

**Potential Implementation:**
- Add `--uncertainty-threshold` CLI parameter
- Check average uncertainty in `_check_stopping_conditions()`
- Stop when `avg_uncertainty < threshold`

**Research Questions:**
- What threshold value indicates sufficient convergence?
- Should we use average uncertainty, max uncertainty, or top-k uncertainty?
- How does early stopping affect ranking quality vs evaluation cost?

**Trade-offs:**
- Pro: Saves evaluations when rankings have converged
- Con: May stop prematurely if uncertainty reduction is non-monotonic
- Con: Adds complexity to stopping logic

This feature was deliberately not implemented to keep the system simple and predictable. Budget-based stopping is easier to reason about and ensures consistent evaluation effort across runs.
