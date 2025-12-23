import globals from "globals";
import eslintConfigPrettier from "eslint-config-prettier";

export default [
  {
    // Apply to all JS files in js/
    files: ["js/**/*.js"],

    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "module",
      globals: {
        ...globals.browser,
        // D3.js global
        d3: "readonly",
      },
    },

    rules: {
      // Possible errors
      "no-console": "off", // Allow console for debugging
      "no-debugger": "warn",
      "no-duplicate-imports": "error",
      "no-template-curly-in-string": "warn",
      "no-unreachable": "error",

      // Best practices
      "eqeqeq": ["error", "always", { null: "ignore" }],
      "no-eval": "error",
      "no-implied-eval": "error",
      "no-return-assign": "error",
      "no-unused-expressions": ["error", { allowShortCircuit: true, allowTernary: true }],
      "prefer-const": ["error", { destructuring: "all" }],

      // Variables
      "no-unused-vars": ["warn", {
        argsIgnorePattern: "^_",
        varsIgnorePattern: "^_",
        caughtErrorsIgnorePattern: "^_"
      }],
      "no-use-before-define": ["error", { functions: false, classes: true }],
      "no-shadow": "warn",

      // ES6+
      "arrow-body-style": ["warn", "as-needed"],
      "no-var": "error",
      "prefer-arrow-callback": "warn",
      "prefer-template": "warn",
    },
  },

  // Disable formatting rules that conflict with Prettier
  eslintConfigPrettier,
];
