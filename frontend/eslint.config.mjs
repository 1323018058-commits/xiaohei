import tsParser from '@typescript-eslint/parser'
import tsPlugin from '@typescript-eslint/eslint-plugin'
import vueParser from 'vue-eslint-parser'
import vuePlugin from 'eslint-plugin-vue'

const browserGlobals = {
  window: 'readonly',
  document: 'readonly',
  navigator: 'readonly',
  console: 'readonly',
  localStorage: 'readonly',
  fetch: 'readonly',
  Headers: 'readonly',
  MutationObserver: 'readonly',
  setTimeout: 'readonly',
  clearTimeout: 'readonly',
  URLSearchParams: 'readonly',
  chrome: 'readonly',
}

const nodeGlobals = {
  process: 'readonly',
  __dirname: 'readonly',
}

export default [
  {
    ignores: [
      'dist/**',
      'node_modules/**',
      'src/auto-imports.d.ts',
      'src/components.d.ts',
      '*.d.ts',
      '.eslintrc.cjs',
    ],
  },
  {
    files: ['src/**/*.{ts,tsx,js,jsx,vue}', 'vite.config.ts'],
    languageOptions: {
      parser: vueParser,
      parserOptions: {
        parser: tsParser,
        ecmaVersion: 'latest',
        sourceType: 'module',
        extraFileExtensions: ['.vue'],
      },
      globals: {
        ...browserGlobals,
        ...nodeGlobals,
      },
    },
    plugins: {
      '@typescript-eslint': tsPlugin,
      vue: vuePlugin,
    },
    rules: {
      'no-undef': 'off',
      'no-unused-vars': 'off',
      '@typescript-eslint/no-explicit-any': 'off',
      '@typescript-eslint/no-unused-vars': ['warn', { argsIgnorePattern: '^_', varsIgnorePattern: '^_' }],
      'vue/multi-word-component-names': 'off',
    },
  },
]
