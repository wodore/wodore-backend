// SVGO configuration for optimizing SVG icons
// Usage: svgo -f assets_src -o assets -config server/apps/categories/svgo.config.js

export default {
  multipass: true, // Run optimizations multiple times for better results

  plugins: [
    // Use default preset optimizations
    "preset-default",

    // Custom resize plugins
    {
      name: "removeAttrs",
      params: {
        attrs: ["svg:width", "svg:height"],
        preserveCurrentColor: false,
      },
    },
    {
      name: "addAttributesToSVGElement",
      params: {
        attributes: [{ width: "48" }, { height: "48" }],
      },
    },
  ],
};
