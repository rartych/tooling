/**
 * Spectral custom function (iterative traversal).
 *
 * Given: "$..requestBody" - targetVal will be the matched requestBody node.
 *
 * Behavior:
 * - Iteratively walk the subtree under the provided requestBody node to find any $ref that
 *   points to "#/components/schemas/<Name>".
 * - For each referenced schema name, check components.schemas.<Name>.description.
 * - If a description exists, emit a result pointing to ["components","schemas",Name,"description"].
 *
 * This implementation avoids recursion to prevent "Maximum call stack size exceeded".
 */

module.exports = function (targetVal, options, ctx) {
  const results = [];

  if (!targetVal || typeof targetVal !== "object") {
    return results;
  }

  // Traverse requestBody subtree iteratively to find $ref occurrences
  const stack = [targetVal];
  const referencedSchemaNames = new Set();

  const schemaRefRegex = /^#\/components\/schemas\/([^\/]+)(?:$|\/)/;

  while (stack.length > 0) {
    const node = stack.pop();
    if (node && typeof node === "object") {
      for (const key of Object.keys(node)) {
        const value = node[key];

        if (key === "$ref" && typeof value === "string") {
          const m = value.match(schemaRefRegex);
          if (m) {
            referencedSchemaNames.add(m[1]);
          }
        }

        if (value && typeof value === "object") {
          stack.push(value);
        }
      }
    }
  }

  if (referencedSchemaNames.size === 0) {
    return results;
  }

  // Obtain the full document to inspect components.schemas
  let doc = null;
  if (ctx) {
    doc = typeof ctx.document === "function" ? ctx.document() : ctx.document;
  }

  if (!doc || !doc.components || !doc.components.schemas) {
    return results;
  }

  const schemas = doc.components.schemas;

  referencedSchemaNames.forEach((schemaName) => {
    const schemaDef = schemas[schemaName];
    if (schemaDef && Object.prototype.hasOwnProperty.call(schemaDef, "description")) {
      results.push({
        message: options && options.message
          ? options.message.replace("{{schema}}", schemaName)
          : `Schema '${schemaName}' is referenced from a requestBody and must not include a description.`,
        path: ["components", "schemas", schemaName, "description"],
      });
    }
  });

  return results;
};
