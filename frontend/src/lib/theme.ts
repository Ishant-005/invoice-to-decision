// Light and dark theme. The theme is the class "dark" on <html>, which switches the colour
// tokens in index.css. Light is the default whatever the operating system prefers; a choice
// is remembered in the browser. A tiny script in index.html applies the remembered choice
// before the page is drawn, so the wrong theme never flashes.

import { useState } from 'react'

export type Theme = 'light' | 'dark'
const STORAGE_KEY = 'theme' // index.html reads the same key

export function currentTheme(): Theme {
  return document.documentElement.classList.contains('dark') ? 'dark' : 'light'
}

function applyTheme(theme: Theme) {
  document.documentElement.classList.toggle('dark', theme === 'dark')
  try {
    localStorage.setItem(STORAGE_KEY, theme)
  } catch {
    // Storage can be blocked (private browsing). The theme still changes for this visit.
  }
}

/** The theme now, and a function that switches to the other one. */
export function useTheme(): [Theme, () => void] {
  const [theme, setTheme] = useState<Theme>(currentTheme)
  const toggle = () => {
    const next = theme === 'dark' ? 'light' : 'dark'
    applyTheme(next)
    setTheme(next)
  }
  return [theme, toggle]
}
