/**
 * Spectral custom function:
 * - Finds all $ref values that occur under requestBody nodes and reference "#/components/schemas/{name}"
 * - For each referenced schema, if components.schemas.{name}.description exists, return a failure pointing at that description node
 *
 * Note: This function intentionally focuses on $ref values that appear anywhere inside requestBody nodes,
 * e.g. requestBody -> content -> application/json -> schema -> $ref
 *
 * It returns an array of result objects with `message` and `path` members as Spectral expects.
 */

module.exports = function (targetVal, options, ctx) {
  const results = [];

  // ctx.document should be the parsed document root (object). Some Spectral versions provide ctx.document
  // directly; others provide a function. Handle common cases.
  let doc = null;
  if (!ctx) {
    return results;
  }
  if (typeof ctx.document === "function") {
    // spectral may provide a getter function
    try {
      doc = ctx.document();
    } catch (e) {
      doc = null;
    }
  } else {
    doc = ctx.document;
  }

  if (!doc || typeof doc !== "object") {
    return results;
  }

  // Collect names of schemas referenced from requestBody $ref
  const referencedSchemaNames = new Set();

  // Recursive walk to find $ref nodes occurring under a requestBody ancestor.
  function walk(node, path = [], inRequestBody = false) {
    if (node && typeof node === "object") {
      // If this node is a requestBody object (key named 'requestBody' or inside a requestBody), set flag
      // We detect entering a requestBody by encountering the key 'requestBody' in the path or current object keys
      // If any key in the current path is 'requestBody', inRequestBody will be true.
      const currentInRequestBody = inRequestBody || path.includes("requestBody");

      for (const key of Object.keys(node)) {
        const value = node[key];
        const childPath = path.concat([key]);

        if (key === "$ref" && typeof value === "string" && currentInRequestBody) {
          // We found a $ref inside a requestBody. Check if it points to components/schemas
          const match = value.match(/^#\/components\/schemas\/([^\/]+)$/);
          if (match) {
            referencedSchemaNames.add(match[1]);
          }
        }

        // Recurse
        if (value && typeof value === "object") {
          walk(value, childPath, currentInRequestBody);
        }
      }
    }
  }

  walk(doc, [], false);

  // For each referenced schema, check whether components.schemas[name].description exists
  const schemas = (doc.components && doc.components.schemas) || {};
  referencedSchemaNames.forEach((schemaName) => {
    const schemaDef = schemas[schemaName];
    if (schemaDef && Object.prototype.hasOwnProperty.call(schemaDef, "description")) {
      // Build the path to the description node to attach the result to that location
      const pathToDescription = ["components", "schemas", schemaName, "description"];
      results.push({
        message: options && options.message
          ? options.message.replace("{{schema}}", schemaName)
          : `Schema '${schemaName}' is referenced from a requestBody and must not include a description.`,
        path: pathToDescription,
      });
    }
  });

  return results;
};
