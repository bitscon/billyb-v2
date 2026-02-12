# Lifecycle State Machine

## States
IDLE → STAGING → VALIDATING → PROMOTING → COMPLETE  
ROLLING_BACK → IDLE  
FAILED → IDLE  
FAILED_HARD (terminal until manual fix)

## State Diagram (Mermaid)

```mermaid
stateDiagram-v2
    IDLE --> STAGING
    STAGING --> VALIDATING
    VALIDATING --> PROMOTING
    PROMOTING --> COMPLETE
    COMPLETE --> IDLE
    STAGING --> FAILED
    VALIDATING --> FAILED
    PROMOTING --> ROLLING_BACK
    ROLLING_BACK --> IDLE
    ROLLING_BACK --> FAILED_HARD
```

## Invariants

- Only one active operation
- FAILED_HARD locks all actions
- State must persist on every transition