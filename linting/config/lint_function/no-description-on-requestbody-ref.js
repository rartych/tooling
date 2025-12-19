/**
 * Spectral custom function that runs for each $ref node found under a requestBody.
 * targetVal is expected to be the $ref string.
 *
 * Behavior:
 * - If the $ref points to "#/components/schemas/<Name>", check components.schemas.<Name>.description.
 * - If a description exists, return a result pointing to that description node.
 */
module.exports = function (targetVal, options, ctx) {
  const results = [];

  if (!targetVal || typeof targetVal !== "string") {
    return results;
  }

  // Only care about local components.schemas refs
  const m = targetVal.match(/^#\/components\/schemas\/([^\/]+)(?:$|\/)/);
  if (!m) {
    return results;
  }
  const schemaName = m[1];

  // Obtain document root
  const doc = ctx && typeof ctx.document === "function" ? ctx.document() : (ctx && ctx.document) || null;
  if (!doc || !doc.components || !doc.components.schemas) {
    return results;
  }

  const schemaDef = doc.components.schemas[schemaName];
  if (!schemaDef) {
    return results;
  }

  if (Object.prototype.hasOwnProperty.call(schemaDef, "description")) {
    results.push({
      message: options && options.message
        ? options.message.replace("{{schema}}", schemaName)
        : `Schema '${schemaName}' is referenced from a requestBody and must not include a description.`,
      path: ["components", "schemas", schemaName, "description"],
    });
  }

  return results;
};
