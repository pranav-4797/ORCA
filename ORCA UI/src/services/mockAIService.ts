import { IAIService, SendMessageOptions, StreamChunk } from './aiService';
import { AgentActivityStep } from '../types/agent';

export class MockAIService implements IAIService {
  private static instance: MockAIService;

  public static getInstance(): MockAIService {
    if (!MockAIService.instance) {
      MockAIService.instance = new MockAIService();
    }
    return MockAIService.instance;
  }

  public async generateTitle(firstMessage: string): Promise<string> {
    const cleaned = firstMessage.trim().replace(/^[^a-zA-Z0-9]+/, '');
    if (cleaned.length < 30) {
      return cleaned.charAt(0).toUpperCase() + cleaned.slice(1);
    }
    const words = cleaned.split(/\s+/).slice(0, 5).join(' ');
    return words.charAt(0).toUpperCase() + words.slice(1) + '...';
  }

  public async sendMessage(options: SendMessageOptions): Promise<string> {
    const { prompt, agentId, model, onChunk, abortSignal } = options;

    // Helper sleep
    const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

    // Phase 1: High-level Agent Activity Simulation
    const steps: { title: string; description?: string }[] = this.getAgentSteps(agentId, prompt);

    for (let i = 0; i < steps.length; i++) {
      if (abortSignal?.aborted) {
        onChunk({ type: 'error', error: 'Generation stopped by user.' });
        return '';
      }

      const stepData: AgentActivityStep = {
        id: `step-${Date.now()}-${i}`,
        title: steps[i].title,
        description: steps[i].description,
        status: 'in_progress',
        timestamp: Date.now()
      };

      onChunk({ type: 'activity', activityStep: stepData });
      await sleep(350 + Math.random() * 250);

      if (abortSignal?.aborted) {
        stepData.status = 'error';
        onChunk({ type: 'activity', activityStep: stepData });
        return '';
      }

      stepData.status = 'completed';
      stepData.durationMs = 280 + Math.floor(Math.random() * 200);
      onChunk({ type: 'activity', activityStep: stepData });
    }

    // Phase 2: Response text construction based on Agent & keywords
    const responseTemplate = this.generateResponseTemplate(agentId, prompt, model);

    // Phase 3: Simulated Streaming of tokens
    // Split into realistic chunks (words / punctuation)
    const chunks = this.chunkText(responseTemplate);
    let fullText = '';

    for (let i = 0; i < chunks.length; i++) {
      if (abortSignal?.aborted) {
        onChunk({ type: 'error', error: 'Generation stopped by user.' });
        return fullText;
      }

      const chunk = chunks[i];
      fullText += chunk;
      onChunk({ type: 'token', content: chunk });

      // Dynamic pacing: slightly longer pause on punctuation / newlines
      let delay = 12 + Math.random() * 14;
      if (chunk.includes('\n') || chunk.includes('.') || chunk.includes(';')) {
        delay += 25;
      }
      await sleep(delay);
    }

    // Phase 4: Done signal
    const promptTokens = Math.ceil(prompt.length / 4);
    const completionTokens = Math.ceil(fullText.length / 4);

    onChunk({
      type: 'done',
      tokens: {
        promptTokens,
        completionTokens,
        totalTokens: promptTokens + completionTokens
      }
    });

    return fullText;
  }

  private getAgentSteps(agentId: string, prompt: string): { title: string; description?: string }[] {
    switch (agentId) {
      case 'coding':
        return [
          { title: 'Parsing code AST and semantic requirements', description: 'Inspecting types and architecture constraints' },
          { title: 'Formulating modular algorithmic solution', description: 'Ensuring zero-leak memory safety and backpressure' },
          { title: 'Generating production TypeScript & test patterns', description: 'Adding error boundaries and typing' }
        ];
      case 'research':
        return [
          { title: 'Deconstructing research query & parameters', description: 'Identifying key technical terminology' },
          { title: 'Searching peer literature & technical specifications', description: 'Cross-verifying consensus models and edge cases' },
          { title: 'Synthesizing structured comparative findings', description: 'Formulating markdown tables and citations' }
        ];
      case 'analyst':
        return [
          { title: 'Extracting data attributes and statistical dimensions', description: 'Validating cohort distributions' },
          { title: 'Computing quantitative metrics & ratio benchmarks', description: 'Evaluating formulas and trends' },
          { title: 'Formatting executive summary and performance tables', description: 'Structuring actionable insights' }
        ];
      case 'reasoning':
        return [
          { title: 'Establishing formal logical premises and invariants', description: 'Constructing inductive base cases' },
          { title: 'Verifying deductive steps and boundary conditions', description: 'Eliminating contradiction possibilities' },
          { title: 'Drafting rigorous step-by-step mathematical proof', description: 'Formatting LaTeX and conclusion' }
        ];
      case 'orca':
        return [
          { title: 'Retrieving real-time AIS telemetry & bathymetric data', description: 'Analyzing UKC and maritime channel restrictions' },
          { title: 'Simulating weather currents and ECA emission constraints', description: 'Evaluating hydrodynamics and bunker consumption' },
          { title: 'Generating mission routing recommendations', description: 'Synthesizing navigation plan and safety margins' }
        ];
      case 'general':
      default:
        return [
          { title: 'Analyzing intent and context', description: 'Identifying target domains and core objectives' },
          { title: 'Formulating comprehensive structured response', description: 'Polishing clarity and actionable guidance' }
        ];
    }
  }

  private generateResponseTemplate(agentId: string, prompt: string, model: string): string {
    const lower = prompt.toLowerCase();

    if (lower.includes('distributed') || lower.includes('raft') || lower.includes('consensus')) {
      return `### Distributed Consensus & Fault Tolerance Overview

A **distributed consensus protocol** guarantees that a cluster of distributed nodes agree on a deterministic state machine sequence despite network partitions, packet loss, or node crashes.

#### Key Architectural Pillars:
1. **Leader Election**: Dynamic heartbeat mechanisms with randomized election timeouts ensure single-leader authority.
2. **Log Replication**: Two-phase write quorum commit guarantees:
   $$\\text{Quorum} = \\lfloor N / 2 \\rfloor + 1$$
3. **Safety Invariants**: An elected leader is guaranteed to contain all previously committed log entries.

\`\`\`typescript
// Distributed Consensus Quorum Validator
export interface NodeCluster {
  nodeId: string;
  isAlive: boolean;
  term: number;
}

export function evaluateQuorum(nodes: NodeCluster[]): boolean {
  const activeCount = nodes.filter(n => n.isAlive).length;
  const quorumThreshold = Math.floor(nodes.length / 2) + 1;
  return activeCount >= quorumThreshold;
}
\`\`\`

> [!TIP]
> Always decouple the consensus log replication path from heavy disk I/O using batching and zero-copy ring buffers to achieve $>50{,}000\\text{ ops/sec}$.`;
    }

    if (lower.includes('worker') || lower.includes('pool') || lower.includes('concurrency') || lower.includes('typescript')) {
      return `### High-Throughput TypeScript Worker Pool

Here is a clean implementation of a bounded **Worker Pool** supporting queue prioritization, timeout guarantees, and cancellation signals.

\`\`\`typescript
export interface Task<T> {
  id: string;
  run: (signal?: AbortSignal) => Promise<T>;
  priority: number;
}

export class TaskRunner<T> {
  private active = 0;
  private queue: Task<T>[] = [];

  constructor(private readonly limit: number = 4) {}

  public enqueue(task: Task<T>): void {
    this.queue.push(task);
    this.queue.sort((a, b) => b.priority - a.priority);
    this.tick();
  }

  private async tick(): Promise<void> {
    if (this.active >= this.limit || this.queue.length === 0) return;
    const item = this.queue.shift()!;
    this.active++;
    try {
      await item.run();
    } finally {
      this.active--;
      this.tick();
    }
  }
}
\`\`\`

### Performance Considerations
- **Memory Footprint**: Bounded queue prevents unbounded heap consumption under burst traffic.
- **Latency**: Zero garbage collection overhead during normal steady-state task recycling.`;
    }

    if (lower.includes('orca') || lower.includes('maritime') || lower.includes('vessel') || lower.includes('route')) {
      return `### ORCA Maritime Intelligence Analysis

**Mission Brief**: Voyage optimization and maritime risk assessment for transit planning.

#### Navigation Assessment Matrix

| Factor | Primary Corridor | Alternative Corridor |
| :--- | :--- | :--- |
| **Passage Distance** | $8{,}420\\text{ NM}$ | $8{,}830\\text{ NM}$ ($+4.8\\%$) |
| **Average Sea State** | Significant Wave Height $\\le 2.2\\text{m}$ | SWH $3.8\\text{m}$ (Monsoon swell) |
| **Fuel Burn (VLSFO)** | $1{,}680\\text{ MT}$ | $1{,}810\\text{ MT}$ |
| **Security Risk** | Standard MARSEC 1 | Enhanced Watch Area |

> [!NOTE]
> Hydrodynamic squall forecast predicts heavy following seas between $04^{\\circ}12'\\text{N}$ and $06^{\\circ}30'\\text{N}$. Engine load modulation recommended to preserve schedule integrity.`;
    }

    // Default response tailored by agent
    if (agentId === 'coding') {
      return `### Implementation & Architecture Solution

Based on your request regarding **"${prompt.slice(0, 45)}..."**, here is the recommended approach with production best practices:

#### 1. Core Implementation

\`\`\`typescript
/**
 * Production-ready modular implementation
 */
export class SolutionHandler {
  private isInitialized = false;

  constructor(private readonly config: { timeoutMs: number }) {}

  public async initialize(): Promise<void> {
    this.isInitialized = true;
    console.info('[Service] Initialized with config:', this.config);
  }

  public execute<T>(payload: T): { success: boolean; data: T; timestamp: number } {
    if (!this.isInitialized) {
      throw new Error('Service must be initialized before execution');
    }
    return {
      success: true,
      data: payload,
      timestamp: Date.now()
    };
  }
}
\`\`\`

#### 2. Key Architecture Benefits
- **Strict Typing**: Full compile-time guarantees preventing runtime state corruption.
- **Modularity**: Clean separation of concerns with dependency injection support.
- **Testability**: Easily mockable in unit and integration suites.

Let me know if you would like me to generate comprehensive unit tests or add persistence hooks!`;
    }

    if (agentId === 'research') {
      return `### Comprehensive Research Synthesis

**Topic Ingestion**: *" ${prompt} "*

#### Key Findings & Literature Synthesis

1. **Foundational Principles**:
   - Modern research emphasizes composability, resilience, and horizontal elasticity.
   - Empirical studies indicate a $35\\%$ reduction in operational overhead when adopting declarative state reconciliation.

2. **Comparative Benchmark Matrix**:

| Metric / Dimension | Traditional Paradigm | Modern AI-Augmented Architecture |
| :--- | :--- | :--- |
| **Throughput** | Fixed linear scaling | Dynamic elastic auto-scaling |
| **Latency ($p99$)** | $>120\\text{ms}$ | $<18\\text{ms}$ |
| **Fault Tolerance** | Active-passive failover | Multi-region active-active |
| **Observability** | Log aggregation | Structured tracing & OpenTelemetry |

> [!IMPORTANT]
> When implementing this in production, verify network topology and enforce rate-limiting at ingress gateways.`;
    }

    if (agentId === 'analyst') {
      return `### Quantitative Data & Strategic Analysis

**Analysis Objective**: Evaluating metrics and projection models for: *"${prompt.slice(0, 40)}..."*

#### Executive Summary Table

| Category | Metric Name | Current Value | Target Q4 | Variance |
| :--- | :--- | :--- | :--- | :--- |
| **Growth** | Monthly Active Usage | $42{,}800$ | $55{,}000$ | $+18.4\\%$ |
| **Efficiency** | Gross Margin | $81.2\\%$ | $80.0\\%$ | $+1.2\\%$ |
| **Retention** | 90-Day Cohort Stickiness | $76.8\\%$ | $75.0\\%$ | $+1.8\\%$ |
| **Velocity** | Average Cycle Time | $3.2\\text{ days}$ | $2.5\\text{ days}$ | $-21.8\\%$ |

#### Actionable Recommendations
1. Focus on accelerating onboarding conversion to capture high-intent cohort expansion.
2. Automate anomaly alerts for variance shifts exceeding $\\pm 5\\%$.`;
    }

    // ORCA onboarding for greetings/short queries
    if (prompt.trim().length < 8 || /^(hi|hello|hey|namaste|help)\b/i.test(prompt.trim())) {
      return `### ORCA Maritime Assistant — How I can help

I answer questions about **Indian coastal waters** using live ocean data and official alerts.

**Try asking:**
- "Is it safe to fish near Ratnagiri tomorrow morning?"
- "Where is the nearest fishing zone off Kochi?"
- "Am I close to a restricted boundary near Visakhapatnam?"
- "Any cyclone or lightning warnings for Odisha?"

*Tip: ensure the ORCA backend is running (\`uvicorn main:app --port 8000\`) so I can fetch live SST, waves, wind, and IMD alerts. Otherwise you are seeing this demo fallback.*`;
    }
    return `> [!IMPORTANT]
> ⚪ Live data unavailable — connect the ORCA backend for a real maritime verdict.

I am in **demo mode** (backend offline). I cannot fetch live waves, wind, or IMD alerts for *"${prompt.slice(0, 80)}"*.

**To get a real answer:** start the backend (\`python -m uvicorn main:app --port 8000\` in ORCA_Backend) and click the header status chip to reconnect. Then ask e.g. "Is it safe near Ratnagiri tomorrow?"`;
  }

  private chunkText(text: string): string[] {
    // Split into smaller segments (tokens/words with spaces)
    const regex = /(\s+|[^\s\w]+|\w+)/g;
    const matches = text.match(regex);
    return matches || [text];
  }
}
