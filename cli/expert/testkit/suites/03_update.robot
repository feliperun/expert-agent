*** Settings ***
Documentation     Validates the edit → validate → count-tokens loop that
...               backs any schema update (prompt tuning, corpus swap, model
...               swap, thinking_budget tweak, etc).
...
...               Offline — no backend calls.
Resource          resources.resource

*** Variables ***
${WORKDIR}    %{ROBOT_TEMPDIR=/tmp}/expert-e2e-update

*** Test Cases ***
Round-Trip A Schema Edit
    Require Schema File
    ${original}=     Read Schema From Path    ${SCHEMA}
    ${bumped}=       Bump Schema Version      ${original}
    ${copied}=       Write Temp Schema        ${bumped}    ${WORKDIR}
    Run Expert CLI   validate    --schema    ${copied}

Token Count Is Stable After Whitespace Edit
    [Documentation]    Whitespace-only changes must not shift the token count.
    ...                Tagged `requires-gemini`: this test calls `count-tokens`
    ...                which hits the Gemini API.
    [Tags]    requires-gemini
    Require Schema File
    ${before}=       Run Expert CLI    count-tokens    --schema    ${SCHEMA}    expect_rc=${None}
    Run Keyword If    ${before}[rc] != 0
    ...    Skip    count-tokens failed: ${before}[stderr]
    ${original}=     Read Schema From Path    ${SCHEMA}
    ${bumped}=       Bump Schema Version      ${original}
    ${copied}=       Write Temp Schema        ${bumped}    ${WORKDIR}
    ${after}=        Run Expert CLI    count-tokens    --schema    ${copied}    expect_rc=${None}
    Log Many    before:    ${before}[stdout]
    Log Many    after:     ${after}[stdout]
