// Compatibility boundary for the existing workspace wiring.
// The settings drawer now renders a focused SettingsPanel instead of the legacy
// all-in-one sidebar that mixed navigation, uploads, tools, memory, and settings.
export {
  CHAT_SETTINGS_DEFAULTS,
  RAG_SETTINGS_DEFAULTS,
  SettingsPanel as Sidebar,
  modeOptions,
} from "../features/settings/SettingsPanel";
