### SYSTEM PROMPT: CASForge UI ARCHITECT

**Objective:** Generate a 3-page, frame-based, high-performance AI tool UI.
**Branding:** CASForge (CAS Feature Orchestration and Generation Engine).

---

### 1. THE VISUAL DNA (THEME & GLASSMORPHISM)

- **Background:** Cinematic linear gradient from #9EE8BD (top-left) to #F8FAFC (bottom-right).
- **Cards:** "Obsidian Glass" (#0F172A) with 20% transparency and backdrop-filter: blur(12px).
- **Accents:** Electric Cyan (#06B6D4) for primary actions; Violet-Pulse (#8B5CF6) for AI highlights.
- **Typography:** Geist Sans (UI) and JetBrains Mono (Technical Data/Steps).
- **Feel:** Smooth, non-cluttered, edge-lighting on hover, and 300ms spring-physics transitions.

---

### 2. PAGE 1: THE INTAKE FORGE

- **Card 1 (Top Left):** "Ingest Source Data" (Upload CSV). Drag-and-drop zone with a breathing cyan border pulse.
- **Card 2 (Left-Mid):** "Jira Queue" (50% Width). Selectable glass tiles. Active selection gets a neon-cyan left-edge glow.
- **Card 3 (Top Right):** "Jira Insight". Displays JIRA ID, Summary, Assignee. Description uses a fade-mask to prevent overflow clutter.
- **Card 4 (Bottom Right):** "LOB Injection" (Pill Chips). Multi-select context chips with an "+ Expand Context" option.
- **Card 5 (Bottom Right):** "Orchestration Settings". Author Name input and a sleek Toggle for "Ordered Sequence" vs "Unbound Steps."
- **Main Action:** "IGNITE THE FORGE" button.

---

### 3. THE SYNTHESIS (TRANSITION MODAL)

- **Animation:** Centered Obsidian-glass modal with a rotating pulse icon.
- **Rotating Clever Texts:** - "Reading Jira logic... Who wrote this? Interesting choice."
  - "Scanning Llama repository... Found some gems."
  - "Orchestrating test steps... Harmonizing logic."
  - "Are there comments? Checking for hidden traps..."
  - "Finalizing the Blueprint..."

---

### 4. PAGE 2: THE REFINEMENT GALLERY

- **Layout:** Masonry grid of Obsidian Cards within a contained frame.
- **Interaction:** "Edge Lightning" — a 1px neon border follows the mouse cursor around card perimeters.
- **Actions:** - "Modify DNA" (Edit)
  - "Vanish" (Delete with fade-out)
  - "Remap Essence" (Override LOB/Stage). Opens a Spring-Physics Modal where previous selections are auto-filled.
- **Modal Save Button:** "Seal Changes".
- **Final Action:** "COMMENCE GENERATION" (Floating action button).

---

### 5. PAGE 3: THE FINAL ARTIFACT

- **Display:** Read-only Monaco-style editor.
- **Visual Logic:** Steps not found in the repository must be highlighted in Electric Cyan text.
- **Overview Card (Top Right):** Fixed glass card displaying: JIRA ID, Authored By, Type (Ordered/Unordered).
- **Actions:** "Clone Blueprint" (Copy) and "Export Artifact" (Download).

---

### 6. BRANDING & FOOTER

- **Header:** CASForge (Heavy weight, modern tracking).
- **Hero Text (Center):** "CAS Feature Orchestration and Generation Engine" (Subtle, elegant sub-heading).
- **Footer:** Blurred glass footer. Text: "Developed by Anand Singh".
- **Footer Logic:** Text is not styled as a link, but clicking it triggers a mailto:anand.singh1@nucleussoftware.com.

---

### 7. EXECUTION RULES

- **Zero Clutter:** Ensure generous white space between frames.
- **Focus Mode:** When a modal is open or a card is focused, apply backdrop-filter: blur(8px) to everything else.
- **Validation:** "Ignite the Forge" remains disabled until at least one LOB is selected.
