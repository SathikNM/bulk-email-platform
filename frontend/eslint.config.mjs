import next from "eslint-config-next";

const config = [
  ...next,
  {
    rules: {
      "react-hooks/exhaustive-deps": "off",
      "react-hooks/set-state-in-effect": "off",
      "@next/next/no-img-element": "off",
    },
  },
  { ignores: [".next/**", "node_modules/**"] },
];
export default config;
