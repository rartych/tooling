#!/usr/bin/env python3
"""
CAMARA API Review Validator v0.6
Automated validation of CAMARA API definitions with comprehensive validation coverage

Features:
- Differentiated validation for explicit vs implicit subscription APIs
- Proper classification of subscription API types
- Targeted validation checks based on API type
- Schema equivalence checking (allows differences in examples/descriptions)
- Comprehensive validation coverage including all CAMARA requirements
- Filename consistency checking
- Improved scope validation
- Test alignment validation
- Multi-file consistency checking
"""

import os
import sys
import yaml
import json
import re
import argparse
from pathlib import Path
from typing import Dict, List, Any, Tuple, Optional
from dataclasses import dataclass, field
from enum import Enum
import datetime
import traceback
from urllib.parse import urlparse

def safe_filename(filename: str, max_length: int = 200) -> str:
    """Sanitize filename to prevent path traversal and other issues"""
    # Remove any path components
    filename = os.path.basename(filename)
    
    # Replace dangerous characters
    filename = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', filename)
    
    # Limit length
    if len(filename) > max_length:
        name, ext = os.path.splitext(filename)
        filename = name[:max_length-len(ext)-3] + "..." + ext
    
    # Ensure it's not empty or just dots
    if not filename or filename.replace('.', '').replace('_', '') == '':
        filename = "sanitized_filename.md"
    
    return filename

def validate_directory_path(path: str) -> str:
    """Validate and normalize directory path"""
    # Convert to absolute path and resolve
    abs_path = os.path.abspath(os.path.expanduser(path))
    
    # Check if path exists
    if not os.path.exists(abs_path):
        raise ValueError(f"Directory does not exist: {abs_path}")
    
    # Check if it's actually a directory
    if not os.path.isdir(abs_path):
        raise ValueError(f"Path is not a directory: {abs_path}")
    
    return abs_path

def sanitize_report_content(content: str) -> str:
    """Sanitize content for safe inclusion in reports"""
    # Escape HTML/XML special characters to prevent injection
    html_escape_table = {
        "&": "&amp;",
        '"': "&quot;",
        "'": "&#x27;",
        ">": "&gt;",
        "<": "&lt;",
    }
    
    # Replace problematic characters
    for char, escape in html_escape_table.items():
        content = content.replace(char, escape)
    
    # Limit content length to prevent DoS
    max_length = 1000000  # 1MB
    if len(content) > max_length:
        content = content[:max_length] + "\n\n⚠️ **Content truncated due to size limits**"
    
    return content

class Severity(Enum):
    CRITICAL = "🔴 Critical"
    MEDIUM = "🟡 Medium"
    LOW = "🔵 Low"
    INFO = "ℹ️ Info"

class APIType(Enum):
    REGULAR = "Regular API"
    IMPLICIT_SUBSCRIPTION = "Implicit Subscription API"
    EXPLICIT_SUBSCRIPTION = "Explicit Subscription API"

@dataclass
class ValidationIssue:
    severity: Severity
    category: str
    description: str
    location: str = ""
    fix_suggestion: str = ""

@dataclass
class ValidationResult:
    file_path: str
    api_name: str = ""
    version: str = ""
    api_type: APIType = APIType.REGULAR
    issues: List[ValidationIssue] = field(default_factory=list)
    checks_performed: List[str] = field(default_factory=list)
    manual_checks_needed: List[str] = field(default_factory=list)
    
    @property
    def critical_count(self) -> int:
        return len([i for i in self.issues if i.severity == Severity.CRITICAL])
    
    @property
    def medium_count(self) -> int:
        return len([i for i in self.issues if i.severity == Severity.MEDIUM])
    
    @property
    def low_count(self) -> int:
        return len([i for i in self.issues if i.severity == Severity.LOW])

@dataclass
class ConsistencyResult:
    issues: List[ValidationIssue] = field(default_factory=list)
    checks_performed: List[str] = field(default_factory=list)

@dataclass
class TestAlignmentResult:
    api_file: str
    test_files: List[str] = field(default_factory=list)
    issues: List[ValidationIssue] = field(default_factory=list)
    checks_performed: List[str] = field(default_factory=list)

class CAMARAAPIValidator:
    """CAMARA API Validator for Commonalities v0.6"""

    def __init__(self, commonalities_version: str = "0.6", review_type: str = "release-candidate"):
        """Initialize validator with version validation"""
        self.expected_commonalities_version = commonalities_version
        self.implemented_version = "0.6"  # This validator only implements v0.6 rules
        self.api_spec = None  # Will store the API spec for reference resolution
        self.review_type = review_type  # Store review type for validation behavior
        self._current_api_name = None  # Store current API name for type detection

        # Warn if requested version doesn't match implemented version
        if self.expected_commonalities_version != self.implemented_version:
            print(f"⚠️ WARNING: This validator implements Commonalities v{self.implemented_version} rules")
            print(f"⚠️ Requested version v{self.expected_commonalities_version} will be validated using v{self.implemented_version} rules")
            print(f"⚠️ For accurate v{self.expected_commonalities_version} validation, please use the appropriate validator script")
    

    def _resolve_reference(self, ref: str, api_spec: dict) -> dict:
        """Resolve $ref reference within the API specification"""
        if not ref.startswith('#/'):
            return {}
        
        # Remove the '#/' prefix and split by '/'
        path_parts = ref[2:].split('/')
        
        current = api_spec
        for part in path_parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return {}
        
        return current if isinstance(current, dict) else {}

    def _get_expected_url_suffix(self, version: str) -> Optional[str]:
        """Convert API version to expected URL suffix according to CAMARA conventions
        
        Returns:
            Expected URL suffix (e.g., '/vwip', '/v0.1rc1', '/v1') or None if version is invalid
        """
        if version == 'wip':
            return '/vwip'
        
        # Validate version format
        if not re.match(r'^\d+\.\d+\.\d+(-rc\.\d+|-alpha\.\d+)?$', version):
            return None
        
        # Parse version components
        version_parts = version.split('.')
        major = int(version_parts[0])
        minor = int(version_parts[1])
        
        # Determine base URL version based on major version
        if major == 0:
            # For 0.x versions, use v{major}.{minor}
            base_version = f"v{major}.{minor}"
        else:
            # For 1.x and above, use v{major} only
            base_version = f"v{major}"
        
        # Handle pre-release suffixes
        if '-rc.' in version:
            rc_num = version.split('-rc.')[1]
            return f"/{base_version}rc{rc_num}"
        elif '-alpha.' in version:
            alpha_num = version.split('-alpha.')[1]
            return f"/{base_version}alpha{alpha_num}"
        else:
            # Stable version
            return f"/{base_version}"
        
    def _check_version_mismatch(self, api_spec: dict, result: ValidationResult):
        """Add warning if validating against different version than requested"""
        if self.expected_commonalities_version != self.implemented_version:
            # Get the declared commonalities version from the API spec
            info = api_spec.get('info', {})
            declared_version = info.get('x-camara-commonalities', 'not specified')
            
            result.issues.append(ValidationIssue(
                Severity.INFO, "Version Mismatch",
                f"Validating with v{self.implemented_version} rules (requested v{self.expected_commonalities_version})",
                "validator",
                f"This validator implements Commonalities v{self.implemented_version} compliance checks"
            ))
            
            # Also check if API declares a different commonalities version
            if declared_version != 'not specified' and declared_version != self.implemented_version:
                result.issues.append(ValidationIssue(
                    Severity.LOW, "Commonalities Version",
                    f"API declares commonalities v{declared_version} but is being validated against v{self.implemented_version} rules",
                    "info.x-camara-commonalities",
                    f"Results may not accurately reflect v{declared_version} compliance"
                ))

    def validate_api_file(self, file_path: str) -> ValidationResult:
        """Validate a single API file"""
        result = ValidationResult(file_path=file_path)
        result.checks_performed.append(f"CAMARA Commonalities {self.expected_commonalities_version} validation")
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                api_spec = yaml.safe_load(f)
            
            # Store API spec for reference resolution
            self.api_spec = api_spec

            # Extract basic info
            info = api_spec.get('info', {})

            # Extract api-name from servers URL (official method)
            api_name = self._extract_api_name_from_servers(api_spec)

            # Fallback to filename if servers extraction fails
            if not api_name:
                api_name = Path(file_path).stem
                result.issues.append(ValidationIssue(
                    Severity.MEDIUM, "Server Configuration",
                    "Cannot extract api-name from servers[*].url",
                    "servers",
                    "Ensure servers[*].url follows format: {apiRoot}/<api-name>/<api-version>"
                ))

            self._current_api_name = api_name
            result.api_name = api_name

            result.version = info.get('version', 'unknown')
            
            # Detect API type first for targeted validation
            result.api_type = self._detect_api_type(api_spec, api_name)
            result.checks_performed.append(f"API type detection: {result.api_type.value}")

            # Check for Commonalities version mismatch
            self._check_version_mismatch(api_spec, result)
            
            # Core validation checks
            self._validate_info_object(api_spec, result)
            self._validate_external_docs(api_spec, result)
            self._validate_servers(api_spec, result)
            self._validate_paths(api_spec, result)
            self._validate_components(api_spec, result)
            self._validate_security_schemes(api_spec, result)
            self._check_version_url_consistency(api_spec, result)
            
            # Checks for Commonalities 0.6
            self._check_updated_generic401(api_spec, result)
            
            # Consistency checks
            self._check_scope_naming_patterns(api_spec, result)
            self._check_filename_consistency(file_path, api_spec, result)
            
            # New comprehensive validation checks
            self._check_mandatory_error_responses(api_spec, result)
            self._check_server_url_format(api_spec, result)
            self._check_commonalities_schema_compliance(api_spec, result)
            self._check_event_subscription_compliance(api_spec, result)
            
            # Apply type-specific validation checks
            if result.api_type == APIType.EXPLICIT_SUBSCRIPTION:
                self._check_explicit_subscription_compliance(api_spec, result)
            elif result.api_type == APIType.IMPLICIT_SUBSCRIPTION:
                self._check_implicit_subscription_compliance(api_spec, result)
            
            # Add manual checks needed based on API type
            result.manual_checks_needed = self._get_manual_checks_for_type(result.api_type)
            
        except yaml.YAMLError as e:
            result.issues.append(ValidationIssue(
                Severity.CRITICAL, "YAML Syntax", f"YAML parsing error: {str(e)}"
            ))
        except Exception as e:
            result.issues.append(ValidationIssue(
                Severity.CRITICAL, "Validation Error", f"Unexpected error: {str(e)}"
            ))
        
        return result

    def _get_manual_checks_for_type(self, api_type: APIType) -> List[str]:
        """Get manual checks needed based on API type"""
        common_checks = [
            "Info.description for device or phone number (if applicable)",
            "Business logic appropriateness review",
            "Documentation quality assessment", 
            "API design patterns validation",
            "Use case coverage evaluation",
            "Security considerations beyond structure",
            "Performance implications assessment"
        ]
        
        if api_type == APIType.EXPLICIT_SUBSCRIPTION:
            return common_checks + [
                "Subscription lifecycle management review",
                "Event delivery mechanism validation", 
                "Webhook endpoint security review",
                "Subscription filtering logic validation"
            ]
        elif api_type == APIType.IMPLICIT_SUBSCRIPTION:
            return common_checks + [
                "Event callback mechanism review",
                "Implicit subscription trigger validation",
                "Event payload structure review"
            ]
        
        return common_checks

    def _detect_api_type(self, api_spec: dict, api_name: str = None) -> APIType:
        """Enhanced API type detection with better subscription pattern recognition"""
        paths = api_spec.get('paths', {})
        
        # Use provided api_name or fall back to stored one
        if api_name is None and hasattr(self, '_current_api_name'):
            api_name = self._current_api_name
        
        # Check if API name follows subscription API naming convention
        is_subscription_api_by_name = False
        if api_name:
            api_name_lower = api_name.lower()
            is_subscription_api_by_name = (
                api_name_lower.endswith('-subscriptions') or 
                api_name_lower.endswith('_subscriptions')
            )
        
        # Check for explicit subscription endpoints
        subscription_patterns = ['/subscriptions', '/subscription']
        for path in paths.keys():
            for pattern in subscription_patterns:
                if pattern in path.lower():
                    return APIType.EXPLICIT_SUBSCRIPTION
        
        # Check for webhook/event patterns in responses or callbacks
        for path, path_obj in paths.items():
            if isinstance(path_obj, dict):
                for method, operation in path_obj.items():
                    if method in ['get', 'post', 'put', 'delete', 'patch'] and isinstance(operation, dict):
                        # Check callbacks (implicit subscription indicator)
                        if 'callbacks' in operation:
                            return APIType.IMPLICIT_SUBSCRIPTION
                        
                        # Check responses for event patterns
                        responses = operation.get('responses', {})
                        for response in responses.values():
                            if isinstance(response, dict):
                                # Check content types for event patterns
                                content = response.get('content', {})
                                for media_type, media_obj in content.items():
                                    if isinstance(media_obj, dict):
                                        schema = media_obj.get('schema', {})
                                        schema_str = str(schema).lower()
                                        if any(keyword in schema_str for keyword in ['webhook', 'event', 'notification', 'callback']):
                                            return APIType.IMPLICIT_SUBSCRIPTION
        
        # Check components for subscription-related schemas
        components = api_spec.get('components', {})
        schemas = components.get('schemas', {})
        has_event_subscription_schema = False
        has_event_schema = False

        for schema_name, schema_def in schemas.items():
            schema_name_lower = schema_name.lower()
            
            # Check for event/notification schemas
            if any(keyword in schema_name_lower for keyword in ['webhook', 'event', 'notification', 'cloudevent']):
                has_event_schema = True
            
            # Check for subscription schemas with SubscriptionId property
            elif 'subscription' in schema_name_lower:
                if isinstance(schema_def, dict):
                    properties = schema_def.get('properties', {})
                    # Event subscription schemas have SubscriptionId
                    if 'subscriptionId' in properties or 'SubscriptionId' in properties:
                        has_event_subscription_schema = True

        # Make decision based on multiple factors
        if has_event_subscription_schema and (is_subscription_api_by_name or 
                                            any('/subscription' in path for path in paths.keys())):
            return APIType.EXPLICIT_SUBSCRIPTION
        elif has_event_schema:
            return APIType.IMPLICIT_SUBSCRIPTION

        return APIType.REGULAR

    def _validate_info_object(self, api_spec: dict, result: ValidationResult):
        """Validate the info object with comprehensive checks"""
        result.checks_performed.append("Info object validation")
        result.checks_performed.append("Authorization template validation") 
        result.checks_performed.append("Error responses template validation")
                
        info = api_spec.get('info', {})
        if not info:
            result.issues.append(ValidationIssue(
                Severity.CRITICAL, "Info Object", 
                "Missing required `info` object"
            ))
            return
        
        # Title validation
        title = info.get('title', '')
        if not title:
            result.issues.append(ValidationIssue(
                Severity.CRITICAL, "Info Object",
                "Missing required `title` field",
                "info.title"
            ))
        elif 'API' in title:
            result.issues.append(ValidationIssue(
                Severity.MEDIUM, "Info Object",
                f"Title should not include 'API': `{title}`",
                "info.title",
                "Remove 'API' from title"
            ))
        
        # Version check (for wip detection)
        version = info.get('version', '')
        if version != 'wip' and not re.match(r'^\d+\.\d+\.\d+(-rc\.\d+|-alpha\.\d+)?$', version):
            result.issues.append(ValidationIssue(
                Severity.CRITICAL, "Info Object",
                f"Invalid version format: `{version}`",
                "info.version",
                "Use semantic versioning (`x.y.z` or `x.y.z-rc.n` or `x.y.z-alpha.n`)"
            ))
        
        # License check
        license_info = info.get('license', {})
        if license_info.get('name') != 'Apache 2.0':
            result.issues.append(ValidationIssue(
                Severity.CRITICAL, "Info Object",
                "License must be `Apache 2.0`",
                "info.license.name"
            ))
        
        if license_info.get('url') != 'https://www.apache.org/licenses/LICENSE-2.0.html':
            result.issues.append(ValidationIssue(
                Severity.CRITICAL, "Info Object",
                "Incorrect license URL",
                "info.license.url"
            ))

        # Mandatory template validations
        description = info.get('description', '')
        self._validate_authorization_template(description, result)
        self._validate_error_responses_template(description, result)

        # Commonalities version
        commonalities = info.get('x-camara-commonalities')
        if str(commonalities) != self.expected_commonalities_version:
            result.issues.append(ValidationIssue(
                Severity.MEDIUM, "Info Object",
                f"Expected commonalities `{self.expected_commonalities_version}`, found: `{commonalities}`",
                "info.x-camara-commonalities"
            ))
        
        # Forbidden fields
        if 'termsOfService' in info:
            result.issues.append(ValidationIssue(
                Severity.MEDIUM, "Info Object",
                "`termsOfService` should not be in the API definition",
                "info.termsOfService",
                "Remove `termsOfService` field"
            ))

    def _normalize_text_for_template_check(self, text: str) -> str:
        """Normalize text for template comparison (remove extra whitespace, make lowercase)"""
        # Remove extra whitespace, normalize line breaks, make lowercase
        normalized = re.sub(r'\s+', ' ', text.strip().lower())
        # Remove common markdown formatting that might vary
        normalized = re.sub(r'[*_`]', '', normalized)
        return normalized

    def _validate_authorization_template(self, description: str, result: ValidationResult):
        """Validate mandatory authorization template in info.description"""
        if not description:
            result.issues.append(ValidationIssue(
                Severity.CRITICAL, "Authorization Template",
                "Missing info.description - required for authorization template",
                "info.description"
            ))
            return
        
        # Required authorization template components
        required_components = [
            "# Authorization and authentication",
            "Camara Security and Interoperability Profile",
            "Identity and Consent Management",
            "github.com/camaraproject/IdentityAndConsentManagement",
            "authorization flows to be used will be agreed upon during the onboarding process",
            "three-legged access tokens is mandatory",
            "privacy regulations"
        ]
        
        # Normalize description for checking
        normalized_desc = self._normalize_text_for_template_check(description)
        
        missing_components = []
        for component in required_components:
            normalized_component = self._normalize_text_for_template_check(component)
            if normalized_component not in normalized_desc:
                missing_components.append(component)
        
        if missing_components:
            result.issues.append(ValidationIssue(
                Severity.CRITICAL, "Authorization Template",
                f"Missing required authorization template components: {', '.join(missing_components)}",
                "info.description",
                "Add the mandatory authorization template as specified in CAMARA-API-access-and-user-consent.md"
            ))
        
        # Check for required header specifically
        if not re.search(r'#\s*Authorization\s+and\s+authentication', description, re.IGNORECASE):
            result.issues.append(ValidationIssue(
                Severity.CRITICAL, "Authorization Template",
                "Missing required '# Authorization and authentication' header",
                "info.description"
            ))

    def _validate_error_responses_template(self, description: str, result: ValidationResult):
        """Validate mandatory error responses template in info.description (new in v0.6)"""
        if not description:
            # Already reported in authorization template check
            return
        
        # Only check this template for v0.6 and above
        try:
            current_version = float(self.expected_commonalities_version)
            if current_version < 0.6:
                return  # Not required for versions before 0.6
        except (ValueError, AttributeError):
            pass  # If version parsing fails, include the check
        
        # Required error responses template components
        required_components = [
            "# Additional CAMARA error responses",
            "not exhaustive",
            "CAMARA API Design Guide",
            "CAMARA_common.yaml",
            "Commonalities Release",
            "API Readiness Checklist",
            "501 - NOT_IMPLEMENTED"
        ]
        
        # Normalize description for checking
        normalized_desc = self._normalize_text_for_template_check(description)
        
        missing_components = []
        for component in required_components:
            normalized_component = self._normalize_text_for_template_check(component)
            if normalized_component not in normalized_desc:
                missing_components.append(component)
        
        if missing_components:
            result.issues.append(ValidationIssue(
                Severity.CRITICAL, "Error Responses Template",
                f"Missing required error responses template components: {', '.join(missing_components)}",
                "info.description",
                "Add the mandatory 'Additional CAMARA error responses' template as specified in CAMARA API Design Guide v0.6"
            ))
        
        # Check for required header specifically
        if not re.search(r'#\s*Additional\s+CAMARA\s+error\s+responses', description, re.IGNORECASE):
            result.issues.append(ValidationIssue(
                Severity.CRITICAL, "Error Responses Template",
                "Missing required '# Additional CAMARA error responses' header",
                "info.description"
            ))

    def _validate_external_docs(self, api_spec: dict, result: ValidationResult):
        """Validate external documentation"""
        result.checks_performed.append("External documentation validation")
        
        external_docs = api_spec.get('externalDocs')
        if not external_docs:
            result.issues.append(ValidationIssue(
                Severity.CRITICAL, "ExternalDocs",
                "Missing externalDocs object",
                "externalDocs",
                "Add externalDocs with description and url"
            ))
            return
        
        if not external_docs.get('description'):
            result.issues.append(ValidationIssue(
                Severity.MEDIUM, "ExternalDocs",
                "Missing externalDocs description",
                "externalDocs.description"
            ))
        
        url = external_docs.get('url', '')
        if not url:
            result.issues.append(ValidationIssue(
                Severity.CRITICAL, "ExternalDocs",
                "Missing externalDocs URL",
                "externalDocs.url"
            ))
        elif not url.startswith('https://'):
            result.issues.append(ValidationIssue(
                Severity.MEDIUM, "ExternalDocs",
                "External docs URL should use HTTPS",
                "externalDocs.url"
            ))

    def _validate_servers(self, api_spec: dict, result: ValidationResult):
        """Validate servers configuration"""
        result.checks_performed.append("Servers validation")
        
        servers = api_spec.get('servers', [])
        if not servers:
            result.issues.append(ValidationIssue(
                Severity.MEDIUM, "Servers",
                "No servers defined",
                "servers"
            ))
            return
        
        for i, server in enumerate(servers):
            url = server.get('url', '')
            if not url:
                result.issues.append(ValidationIssue(
                    Severity.CRITICAL, "Servers",
                    f"Server {i+1} missing URL",
                    f"servers[{i}].url"
                ))
            elif not url.startswith(('https://', '{apiRoot}')):
                result.issues.append(ValidationIssue(
                    Severity.MEDIUM, "Servers",
                    f"Server URL should use HTTPS or template: `{url}`",
                    f"servers[{i}].url"
                ))

    def _validate_paths(self, api_spec: dict, result: ValidationResult):
        """Validate paths object with comprehensive operation checks"""
        result.checks_performed.append("Paths validation")
        
        paths = api_spec.get('paths', {})
        if not paths:
            result.issues.append(ValidationIssue(
                Severity.CRITICAL, "Paths",
                "No paths defined"
            ))
            return
        
        # Get api_name for security validation
        api_name = self._current_api_name if hasattr(self, '_current_api_name') else ''
        
        for path, path_obj in paths.items():
            if not isinstance(path_obj, dict):
                continue
                
            for method, operation in path_obj.items():
                if method in ['get', 'post', 'put', 'delete', 'patch', 'head', 'options', 'trace']:
                    self._validate_operation(operation, f"{method.upper()} {path}", result)
                    
                    # Add security validation with proper parameters
                    if isinstance(operation, dict):
                        self._validate_operation_security(operation, path, method, api_name, result)

    def _validate_operation(self, operation: dict, operation_name: str, result: ValidationResult):
        """Validate individual operation with detailed checks"""
        if not isinstance(operation, dict):
            return
        
        # Check for operationId
        if 'operationId' not in operation:
            result.issues.append(ValidationIssue(
                Severity.CRITICAL, "Operation",
                "Missing operationId",
                operation_name
            ))
        
        # Check summary and description
        if 'summary' not in operation:
            result.issues.append(ValidationIssue(
                Severity.MEDIUM, "Operation",
                "Missing summary",
                operation_name
            ))
        
        if 'description' not in operation:
            result.issues.append(ValidationIssue(
                Severity.LOW, "Operation",
                "Missing description",
                operation_name
            ))
        
        # Check responses
        responses = operation.get('responses', {})
        if not responses:
            result.issues.append(ValidationIssue(
                Severity.CRITICAL, "Operation",
                "No responses defined",
                operation_name
            ))
        else:
            self._validate_responses(responses, operation_name, result)
        
        # Check security for operations that need it
        security = operation.get('security')
        if security is None and operation_name.startswith(('POST', 'PUT', 'DELETE')):
            result.issues.append(ValidationIssue(
                Severity.MEDIUM, "Operation",
                "Consider adding security requirements for modifying operations",
                operation_name
            ))

    def _validate_responses(self, responses: dict, operation_name: str, result: ValidationResult):
        """Validate response definitions"""
        # Check for success response
        success_codes = ['200', '201', '202', '204']
        has_success = any(code in responses for code in success_codes)
        
        if not has_success:
            result.issues.append(ValidationIssue(
                Severity.MEDIUM, "Responses",
                "No success response (2xx) defined",
                f"{operation_name}.responses"
            ))
        
        # Check for error responses
        error_codes = ['400', '401', '403', '404']
        for code in error_codes:
            if code in responses:
                response = responses[code]
                if isinstance(response, dict):
                    self._validate_error_response(response, code, operation_name, result)

    def _validate_error_response(self, response: dict, status_code: str, operation_name: str, result: ValidationResult):
        """Validate error response structure"""
        content = response.get('content', {})
        
        # Check for application/json content type
        if 'application/json' not in content:
            result.issues.append(ValidationIssue(
                Severity.MEDIUM, "Error Responses",
                f"Error response {status_code} should have application/json content",
                f"{operation_name}.responses.{status_code}"
            ))
            return
        
        # Check for ErrorInfo schema reference
        json_content = content.get('application/json', {})
        schema = json_content.get('schema', {})
        
        if isinstance(schema, dict):
            ref = schema.get('$ref', '')
            if '#/components/schemas/ErrorInfo' not in ref:
                result.issues.append(ValidationIssue(
                    Severity.MEDIUM, "Error Responses",
                    f"Error response {status_code} should reference ErrorInfo schema",
                    f"{operation_name}.responses.{status_code}"
                ))

    def _validate_error_response(self, response: dict, status_code: str, operation_name: str, result: ValidationResult):
        """Validate error response structure with $ref resolution"""
        
        # Handle $ref in response
        if '$ref' in response:
            ref_path = response['$ref']
            resolved_response = self._resolve_reference(ref_path, self.api_spec)
            if resolved_response:
                # Recursively validate the resolved response
                self._validate_error_response(resolved_response, status_code, operation_name, result)
                return
            else:
                result.issues.append(ValidationIssue(
                    Severity.CRITICAL, "Error Responses",
                    f"Cannot resolve response reference: {ref_path}",
                    f"{operation_name}.responses.{status_code}"
                ))
                return
        
        content = response.get('content', {})
        
        # Check for application/json content type
        if 'application/json' not in content:
            result.issues.append(ValidationIssue(
                Severity.MEDIUM, "Error Responses",
                f"Error response {status_code} should have application/json content",
                f"{operation_name}.responses.{status_code}"
            ))
            return
        
        # Check for ErrorInfo schema reference
        json_content = content.get('application/json', {})
        schema = json_content.get('schema', {})
        
        if isinstance(schema, dict):
            # Handle schema with $ref
            if '$ref' in schema:
                ref = schema.get('$ref', '')
                if '#/components/schemas/ErrorInfo' not in ref:
                    result.issues.append(ValidationIssue(
                        Severity.MEDIUM, "Error Responses",
                        f"Error response {status_code} should reference ErrorInfo schema",
                        f"{operation_name}.responses.{status_code}"
                    ))
            # Handle schema with allOf containing ErrorInfo reference
            elif 'allOf' in schema:
                all_of_items = schema.get('allOf', [])
                has_error_info = False
                for item in all_of_items:
                    if isinstance(item, dict) and '$ref' in item:
                        if '#/components/schemas/ErrorInfo' in item['$ref']:
                            has_error_info = True
                            break
                
                if not has_error_info:
                    result.issues.append(ValidationIssue(
                        Severity.MEDIUM, "Error Responses",
                        f"Error response {status_code} should reference ErrorInfo schema",
                        f"{operation_name}.responses.{status_code}"
                    ))
            else:
                result.issues.append(ValidationIssue(
                    Severity.MEDIUM, "Error Responses",
                    f"Error response {status_code} should reference ErrorInfo schema",
                    f"{operation_name}.responses.{status_code}"
                ))

    def _validate_components(self, api_spec: dict, result: ValidationResult):
        """Validate components section"""
        result.checks_performed.append("Components validation")
        
        components = api_spec.get('components', {})
        if not components:
            result.issues.append(ValidationIssue(
                Severity.MEDIUM, "Components",
                "No components defined"
            ))
            return
        
        # Store api_spec reference for cross-method validation
        self.api_spec = api_spec

        # Check schemas
        schemas = components.get('schemas', {})
        self._validate_schemas(schemas, result)
        
        # Check security schemes
        security_schemes = components.get('securitySchemes', {})
        self._validate_security_schemes_section(security_schemes, result)

    def _validate_schemas(self, schemas: dict, result: ValidationResult):
        """Validate schema definitions"""
        # Check for required common schemas
        required_schemas = ['ErrorInfo', 'XCorrelator']
        
        for schema_name in required_schemas:
            if schema_name not in schemas:
                result.issues.append(ValidationIssue(
                    Severity.CRITICAL, "Components",
                    f"Missing required `{schema_name}` schema",
                    "components.schemas"
                ))
        
        # Validate ErrorInfo schema structure if present
        if 'ErrorInfo' in schemas:
            self._validate_error_info_schema(schemas['ErrorInfo'], result)
        
        # Check for deprecated schemas
        deprecated_patterns = ['IDENTIFIER_MISMATCH']
        for schema_name, schema_def in schemas.items():
            if isinstance(schema_def, dict):
                # Check for deprecated error codes in enum values
                if 'enum' in schema_def:
                    enum_values = schema_def.get('enum', [])
                    for deprecated in deprecated_patterns:
                        if deprecated in enum_values:
                            result.issues.append(ValidationIssue(
                                Severity.CRITICAL, "Error Responses",
                                f"Forbidden error code `{deprecated}` found",
                                f"components.schemas.{schema_name}",
                                f"Remove `{deprecated}` from enum values"
                            ))

    def _validate_error_info_schema(self, error_info_schema: dict, result: ValidationResult):
        """Validate ErrorInfo schema structure for v0.6 compliance"""
        if not isinstance(error_info_schema, dict):
            return
        
        required_properties = ['code', 'message']
        properties = error_info_schema.get('properties', {})
        
        for prop in required_properties:
            if prop not in properties:
                result.issues.append(ValidationIssue(
                    Severity.CRITICAL, "ErrorInfo Schema",
                    f"Missing required property `{prop}`",
                    "components.schemas.ErrorInfo.properties"
                ))

    def _validate_security_schemes_section(self, security_schemes: dict, result: ValidationResult):
        """Validate security schemes section"""
        # Use existing API type detection
        api_type = self._detect_api_type(self.api_spec)
        is_subscription_api = api_type in [APIType.IMPLICIT_SUBSCRIPTION, APIType.EXPLICIT_SUBSCRIPTION]
        
        # Check for required openId scheme
        if 'openId' not in security_schemes:
            result.issues.append(ValidationIssue(
                Severity.CRITICAL, "Security Schemes",
                "Missing required 'openId' security scheme",
                "components.securitySchemes",
                "Add openId scheme with type: openIdConnect"
            ))
        
        # For subscription APIs, check for notificationsBearerAuth
        if is_subscription_api and 'notificationsBearerAuth' not in security_schemes:
            result.issues.append(ValidationIssue(
                Severity.CRITICAL, "Security Schemes",
                "Subscription APIs must include 'notificationsBearerAuth' security scheme",
                "components.securitySchemes",
                "Add notificationsBearerAuth scheme for callback authentication"
            ))
        
        for scheme_name, scheme_def in security_schemes.items():
            if isinstance(scheme_def, dict):
                scheme_type = scheme_def.get('type')
                
                if scheme_type == 'openIdConnect':
                    self._validate_openid_connect_scheme(scheme_def, scheme_name, result)
                    
                    # Check naming convention
                    if scheme_name != 'openId':
                        result.issues.append(ValidationIssue(
                            Severity.MEDIUM, "Security Schemes",
                            f"OpenID Connect scheme should be named 'openId', found '{scheme_name}'",
                            f"components.securitySchemes.{scheme_name}"
                        ))
                
                elif scheme_type == 'http' and scheme_name == 'notificationsBearerAuth':
                    self._validate_notifications_bearer_auth_scheme(scheme_def, scheme_name, result)
                
                elif scheme_type == 'oauth2':
                    result.issues.append(ValidationIssue(
                        Severity.CRITICAL, "Security Schemes",
                        f"Use 'openIdConnect' type instead of 'oauth2' for scheme '{scheme_name}'",
                        f"components.securitySchemes.{scheme_name}.type",
                        "CAMARA requires OpenID Connect, not OAuth2"
                    ))
                
                elif scheme_type not in ['openIdConnect', 'http']:
                    result.issues.append(ValidationIssue(
                        Severity.MEDIUM, "Security Schemes",
                        f"Unexpected security scheme type '{scheme_type}' for '{scheme_name}'",
                        f"components.securitySchemes.{scheme_name}.type"
                    ))


    def _validate_openid_connect_scheme(self, scheme_def: dict, scheme_name: str, result: ValidationResult):
        """Validate OpenID Connect security scheme"""
        # Check for required openIdConnectUrl
        if 'openIdConnectUrl' not in scheme_def:
            result.issues.append(ValidationIssue(
                Severity.CRITICAL, "Security Schemes",
                f"OpenID Connect scheme `{scheme_name}` missing openIdConnectUrl",
                f"components.securitySchemes.{scheme_name}.openIdConnectUrl"
            ))
            return
        
        # Validate URL format
        connect_url = scheme_def.get('openIdConnectUrl', '')
        if not connect_url.startswith(('https://', 'http://')):
            result.issues.append(ValidationIssue(
                Severity.MEDIUM, "Security Schemes",
                f"OpenID Connect URL should use HTTPS: `{connect_url}`",
                f"components.securitySchemes.{scheme_name}.openIdConnectUrl"
            ))
        
        # Check for well-known endpoint pattern
        if '.well-known/openid-configuration' not in connect_url:
            result.issues.append(ValidationIssue(
                Severity.MEDIUM, "Security Schemes",
                f"OpenID Connect URL should point to well-known configuration: `{connect_url}`",
                f"components.securitySchemes.{scheme_name}.openIdConnectUrl"
            ))

    def _validate_notifications_bearer_auth_scheme(self, scheme_def: dict, scheme_name: str, result: ValidationResult):
        """Validate notificationsBearerAuth security scheme for subscription APIs"""
        # Check type
        if scheme_def.get('type') != 'http':
            result.issues.append(ValidationIssue(
                Severity.CRITICAL, "Security Schemes",
                f"Notifications Bearer Auth scheme `{scheme_name}` must have type 'http'",
                f"components.securitySchemes.{scheme_name}.type"
            ))
        
        # Check scheme
        if scheme_def.get('scheme') != 'bearer':
            result.issues.append(ValidationIssue(
                Severity.CRITICAL, "Security Schemes",
                f"Notifications Bearer Auth scheme `{scheme_name}` must have scheme 'bearer'",
                f"components.securitySchemes.{scheme_name}.scheme"
            ))
        
        # Check bearerFormat (should reference sinkCredential)
        bearer_format = scheme_def.get('bearerFormat', '')
        if 'sinkCredential' not in bearer_format:
            result.issues.append(ValidationIssue(
                Severity.MEDIUM, "Security Schemes",
                f"Notifications Bearer Auth scheme `{scheme_name}` should reference sinkCredential in bearerFormat",
                f"components.securitySchemes.{scheme_name}.bearerFormat"
            ))

    def _validate_operation_security(self, operation: dict, path: str, method: str, 
                                api_name: str, result: ValidationResult):
        """Validate security settings for an operation"""
        
        # Construct operation_name from path and method
        operation_name = f"{method.upper()} {path}"
        
        # Get security requirements
        security = operation.get('security', [])
        
        # Check if this is a callback operation FIRST (applies to all API types)
        is_callback = 'callbacks' in operation_name.lower() or 'notification' in operation_name.lower()
        
        if is_callback:
            # Callback operations MUST support notificationsBearerAuth and MAY have empty security
            if security is None:
                result.issues.append(ValidationIssue(
                    Severity.CRITICAL, "Operation Security",
                    f"Callback operation must have security requirements with notificationsBearerAuth: {operation_name}",
                    f"{operation_name}.security"
                ))
            else:
                has_notifications_bearer_auth = False
                has_empty_security = False
                
                for security_req in security:
                    if isinstance(security_req, dict):
                        if not security_req:  # Empty security object
                            has_empty_security = True
                        elif 'notificationsBearerAuth' in security_req:
                            has_notifications_bearer_auth = True
                
                # MUST have notificationsBearerAuth
                if not has_notifications_bearer_auth:
                    result.issues.append(ValidationIssue(
                        Severity.CRITICAL, "Operation Security",
                        f"Callback operation must include notificationsBearerAuth: {operation_name}",
                        f"{operation_name}.security",
                        "Add notificationsBearerAuth to security requirements"
                    ))
                
                # Validate that it's not ONLY empty security
                if has_empty_security and not has_notifications_bearer_auth:
                    result.issues.append(ValidationIssue(
                        Severity.CRITICAL, "Operation Security",
                        f"Callback operation cannot have only empty security, must include notificationsBearerAuth: {operation_name}",
                        f"{operation_name}.security"
                    ))
            return  # Done with callback validation
        
        # For non-callback operations, check API type
        api_type = self._detect_api_type(self.api_spec, api_name)
        
        # For explicit subscription APIs, use special validation
        if api_type == APIType.EXPLICIT_SUBSCRIPTION:
            self._validate_explicit_subscription_scopes(operation, path, method, api_name, result)
            return
        
        # For other API types (regular and implicit subscription), validate standard security
        if security:
            # For regular operations with security, validate they use openId
            has_openid = False
            for security_req in security:
                if isinstance(security_req, dict) and 'openId' in security_req:
                    has_openid = True
                    
                    # Also validate scope naming pattern for regular APIs
                    scopes = security_req['openId']
                    if isinstance(scopes, list):
                        for scope_name in scopes:
                            if not re.match(r'^[a-z0-9-]+:[a-z0-9-]+(?::[a-z0-9-]+)?$', scope_name):
                                result.issues.append(ValidationIssue(
                                    Severity.MEDIUM, "Scope Naming",
                                    f"Scope name should follow pattern `api-name:[resource:]action`: `{scope_name}`",
                                    f"{operation_name}.security"
                                ))
                    break
            
            if not has_openid:
                result.issues.append(ValidationIssue(
                    Severity.MEDIUM, "Operation Security",
                    f"Operation should use 'openId' security scheme: {operation_name}",
                    f"{operation_name}.security"
                ))

    def _validate_explicit_subscription_scopes(self, operation: dict, path: str, method: str, 
                                            api_name: str, result: ValidationResult):
        """Validate scopes for explicit subscription APIs according to CAMARA guidelines
        
        For explicit subscription APIs:
        - CREATE operations: api-name:event-type:create
        - READ operations: api-name:read
        - DELETE operations: api-name:delete
        """
        security = operation.get('security', [])
        
        for security_item in security:
            if isinstance(security_item, dict) and 'openId' in security_item:
                scopes = security_item['openId']
                
                if not isinstance(scopes, list):
                    continue
                
                for scope in scopes:
                    # Determine expected scope pattern based on operation
                    if method.lower() == 'post' and path.endswith('/subscriptions'):
                        # CREATE operation - should have event type in scope
                        if not self._is_valid_event_subscription_create_scope(scope, api_name):
                            result.issues.append(ValidationIssue(
                                Severity.MEDIUM, "Scope Naming",
                                f"Event subscription creation scope should follow pattern `api-name:event-type:create`: `{scope}`",
                                f"{method.upper()} {path}.security",
                                "Use format: api-name:org.camaraproject.api-name.version.event-name:create"
                            ))
                    
                    elif method.lower() == 'get':
                        # READ operation
                        expected_scope = f"{api_name}:read"
                        if scope != expected_scope:
                            result.issues.append(ValidationIssue(
                                Severity.MEDIUM, "Scope Naming",
                                f"Event subscription read scope should be `{expected_scope}`, found: `{scope}`",
                                f"{method.upper()} {path}.security"
                            ))
                    
                    elif method.lower() == 'delete':
                        # DELETE operation
                        expected_scope = f"{api_name}:delete"
                        if scope != expected_scope:
                            result.issues.append(ValidationIssue(
                                Severity.MEDIUM, "Scope Naming",
                                f"Event subscription delete scope should be `{expected_scope}`, found: `{scope}`",
                                f"{method.upper()} {path}.security"
                            ))

    def _is_valid_event_subscription_create_scope(self, scope: str, api_name: str) -> bool:
        """Check if a scope follows the event subscription create pattern
        
        Pattern: api-name:event-type:create
        Where event-type is like: org.camaraproject.api-name.version.event-name
        """
        parts = scope.split(':')
        
        # Should have exactly 3 parts: api-name:event-type:create
        if len(parts) != 3:
            return False
        
        scope_api_name, event_type, action = parts
        
        # Check api name matches
        if scope_api_name != api_name:
            return False
        
        # Check action is 'create'
        if action != 'create':
            return False
        
        # Check event type format (org.camaraproject.api-name.version.event-name)
        if not event_type.startswith('org.camaraproject.'):
            return False
        
        # Optionally, verify the event type exists in the API spec
        if hasattr(self, 'api_spec'):
            # Look for the event type in the API's defined event types
            if not self._event_type_exists_in_spec(event_type):
                return False
        
        return True

    def _event_type_exists_in_spec(self, event_type: str) -> bool:
        """Check if an event type is defined in the API specification"""
        # Look in common places where event types are defined
        paths_to_check = [
            ['components', 'schemas', 'SubscriptionEventType', 'enum'],
            ['components', 'schemas', 'EventTypeNotification', 'enum'],
            # Add more paths as needed based on API structure
        ]
        
        for path in paths_to_check:
            current = self.api_spec
            for key in path:
                if isinstance(current, dict) and key in current:
                    current = current[key]
                else:
                    current = None
                    break
            
            if isinstance(current, list) and event_type in current:
                return True
        
        return True  # Default to true if we can't find the enum

    def _validate_security_schemes(self, api_spec: dict, result: ValidationResult):
        """Validate top-level security configuration"""
        result.checks_performed.append("Security configuration validation")
        
        security = api_spec.get('security', [])
        components = api_spec.get('components', {})
        security_schemes = components.get('securitySchemes', {})
        
        # Check if security references exist in components
        for security_req in security:
            if isinstance(security_req, dict):
                for scheme_name in security_req.keys():
                    if scheme_name not in security_schemes:
                        result.issues.append(ValidationIssue(
                            Severity.CRITICAL, "Security Schemes",
                            f"Undefined security scheme `{scheme_name}` referenced",
                            "security",
                            f"Define `{scheme_name}` in components.securitySchemes"
                        ))

    def _check_scope_naming_patterns(self, api_spec: dict, result: ValidationResult):
        """Check scope naming patterns for consistency"""
        
        # Skip this check entirely for explicit subscription APIs
        # They have their own validation in _validate_operation_security
        api_type = self._detect_api_type(api_spec)
        if api_type == APIType.EXPLICIT_SUBSCRIPTION:
            return
        
        result.checks_performed.append("Scope naming pattern validation")
        
        components = api_spec.get('components', {})
        security_schemes = components.get('securitySchemes', {})
        
        for scheme_name, scheme_def in security_schemes.items():
            if isinstance(scheme_def, dict):
                scheme_type = scheme_def.get('type')
                
                if scheme_type == 'openIdConnect':
                    # OpenID Connect doesn't define scopes in the scheme itself
                    # Scope validation happens at operation level through security requirements
                    continue
                elif scheme_type == 'oauth2':
                    # Direct OAuth2 schemes are not used in CAMARA (OpenID Connect is used instead)
                    # This will be flagged as critical error in security schemes validation
                    # Skip scope validation for OAuth2 schemes
                    continue
                # For other scheme types (like 'http' for notificationsBearerAuth), no scope validation needed
        
        # Validate scopes at operation level instead
        paths = api_spec.get('paths', {})
        for path, path_obj in paths.items():
            if isinstance(path_obj, dict):
                for method, operation in path_obj.items():
                    if method in ['get', 'post', 'put', 'delete', 'patch'] and isinstance(operation, dict):
                        security = operation.get('security', [])
                        for security_req in security:
                            if isinstance(security_req, dict):
                                for scheme_name, scopes in security_req.items():
                                    if isinstance(scopes, list):
                                        for scope_name in scopes:
                                            # Check kebab-case pattern for scopes
                                            if not re.match(r'^[a-z0-9-]+:[a-z0-9-]+(?::[a-z0-9-]+)?$', scope_name):
                                                result.issues.append(ValidationIssue(
                                                    Severity.MEDIUM, "Scope Naming",
                                                    f"Scope name should follow pattern `api-name:[resource:]action`: `{scope_name}`",
                                                    f"{method.upper()} {path}.security"
                                                ))

    def _extract_api_name_from_servers(self, api_spec: dict) -> Optional[str]:
        """Extract api-name from servers[*].url property
        
        According to CAMARA guidelines:
        - api-name is specified as the base path, prior to the API version, in servers[*].url
        - Format: {apiRoot}/<api-name>/<api-version>
        - Example: {apiRoot}/location-verification/v1 -> api-name is "location-verification"
        """
        servers = api_spec.get('servers', [])
        if not servers:
            return None
        
        api_names = set()
        
        for server in servers:
            url = server.get('url', '')
            if not url:
                continue
            
            # Remove {apiRoot} prefix if present
            if url.startswith('{apiRoot}/'):
                path = url[10:]  # Remove '{apiRoot}/'
            elif url.startswith('http://') or url.startswith('https://'):
                # Extract path from full URL
                parsed = urlparse(url)
                path = parsed.path.lstrip('/')
            else:
                # Assume it's just the path part
                path = url.lstrip('/')
            
            # Split path components
            path_parts = [part for part in path.split('/') if part]
            
            if len(path_parts) >= 2:
                # Format: <api-name>/<api-version>
                api_name = path_parts[0]
                api_names.add(api_name)
            elif len(path_parts) == 1:
                # Only one component - could be api-name without version
                api_name = path_parts[0]
                # Check if it looks like a version (starts with 'v' followed by numbers/dots)
                if not re.match(r'^v\d+', api_name):
                    api_names.add(api_name)
        
        # All servers should have the same api-name
        if len(api_names) == 1:
            return api_names.pop()
        elif len(api_names) > 1:
            # Multiple different api-names found - this is an error but return the first one
            return sorted(api_names)[0]
        else:
            return None

    def _check_filename_consistency(self, file_path: str, api_spec: dict, result: ValidationResult):
        """Check filename consistency with API content"""
        result.checks_performed.append("Filename consistency validation")
        
        filename = Path(file_path).stem
        
        # Check kebab-case
        if not re.match(r'^[a-z0-9-]+$', filename):
            result.issues.append(ValidationIssue(
                Severity.CRITICAL, "File Naming",
                f"Filename should use kebab-case: `{filename}`",
                file_path,
                "Use lowercase letters, numbers, and hyphens only"
            ))
        
        # Extract api-name from servers URL (this is the correct reference)
        api_name = self._extract_api_name_from_servers(api_spec)
        
        if api_name:
            # Validate filename against api-name (primary check)
            if filename != api_name:
                result.issues.append(ValidationIssue(
                    Severity.CRITICAL, "File Naming",
                    f"Filename `{filename}` doesn't match api-name `{api_name}` from servers URL",
                    file_path,
                    f"Rename file to `{api_name}.yaml` to match the api-name from servers[*].url"
                ))
            
            # Validate title consistency with api-name (additional check)
            info = api_spec.get('info', {})
            title = info.get('title', '')
            
            if title:
                # Convert api-name to expected title format for comparison
                # Example: "location-verification" -> "Location Verification"
                expected_title_pattern = api_name.replace('-', ' ').title()
                
                # Also check if title contains the api-name concept
                title_lower = title.lower()
                api_name_words = api_name.replace('-', ' ')
                
                # If title doesn't contain the key concepts from api-name, flag it
                if (api_name_words not in title_lower and 
                    not any(word in title_lower for word in api_name.split('-') if len(word) > 3)):
                    result.issues.append(ValidationIssue(
                        Severity.LOW, "API Consistency",
                        f"API title `{title}` may not align with api-name `{api_name}`",
                        "info.title",
                        f"Consider if title should reference concepts from api-name `{api_name}`"
                    ))
        else:
            # If we can't extract api-name, fall back to basic validation
            result.issues.append(ValidationIssue(
                Severity.MEDIUM, "Server Configuration",
                "Cannot extract api-name from servers[*].url for filename validation",
                "servers",
                "Ensure servers[*].url follows format: {apiRoot}/<api-name>/<api-version>"
            ))
            
            # Still check against title as a fallback (but with lower severity)
            info = api_spec.get('info', {})
            title = info.get('title', '').lower()
            
            if title:
                # Convert title to potential filename format
                title_as_filename = re.sub(r'[^a-z0-9]+', '-', title).strip('-')
                
                if title_as_filename and filename != title_as_filename:
                    result.issues.append(ValidationIssue(
                        Severity.INFO, "File Naming",
                        f"Filename `{filename}` doesn't match title pattern `{title_as_filename}`",
                        file_path,
                        "Consider aligning filename with API title (as fallback when api-name unavailable)"
                    ))

    def _check_version_url_consistency(self, api_spec: dict, result: ValidationResult):
        """Check consistency between API version and server URL suffix"""
        result.checks_performed.append("Version-URL consistency validation")
        
        version = api_spec.get('info', {}).get('version', '')
        servers = api_spec.get('servers', [])
        
        if not servers:
            return
            
        server_url = servers[0].get('url', '')
        
        # Extract the version part from the server URL
        # Expected formats: {apiRoot}/api-name/version
        url_parts = server_url.split('/')
        url_version = url_parts[-1] if url_parts else ''
        
        if self.review_type == "wip":
            # For WIP reviews, expect "wip" version
            if version != 'wip':
                result.issues.append(ValidationIssue(
                    Severity.MEDIUM, "Version",
                    f"WIP review expects version `wip`, found: `{version}`",
                    "info.version",
                    "Use version `wip` for work-in-progress development"
                ))
            
            # Check server URL should end with /vwip
            if not server_url.endswith('/vwip'):
                result.issues.append(ValidationIssue(
                    Severity.MEDIUM, "Server URL",
                    "WIP review expects server URL to end with `/vwip`",
                    "servers[0].url",
                    "Use `/vwip` suffix in server URL for work-in-progress development"
                ))
        else:
            # For release-candidate and other reviews
            if version == 'wip':
                result.issues.append(ValidationIssue(
                    Severity.CRITICAL, "Version",
                    "Work-in-progress version `wip` cannot be released",
                    "info.version",
                    "Update to proper semantic version (e.g., `0.1.0-rc.1`)"
                ))
            
            # Check server URL matches version type using helper
            expected_suffix = self._get_expected_url_suffix(version)
            
            if expected_suffix and not server_url.endswith(expected_suffix):
                # Check for common mistakes
                if server_url.endswith('/wip'):
                    result.issues.append(ValidationIssue(
                        Severity.CRITICAL, "Server URL",
                        f"Invalid work-in-progress URL suffix `/wip`",
                        "servers[0].url",
                        f"For version `{version}`, use `{expected_suffix}`"
                    ))
                elif server_url.endswith('/vwip'):
                    result.issues.append(ValidationIssue(
                        Severity.CRITICAL, "Server URL",
                        f"Version `{version}` cannot use work-in-progress URL suffix `/vwip`",
                        "servers[0].url",
                        f"Update server URL to end with `{expected_suffix}`"
                    ))
                else:
                    result.issues.append(ValidationIssue(
                        Severity.CRITICAL, "Server URL",
                        f"Server URL version `{url_version}` doesn't match API version `{version}`",
                        "servers[0].url",
                        f"Update server URL to end with `{expected_suffix}`"
                    ))

    def _check_updated_generic401(self, api_spec: dict, result: ValidationResult):
        """Check for updated generic 401 error handling in Commonalities 0.6"""
        result.checks_performed.append("Generic 401 error validation (v0.6)")
        
        # Look for 401 responses and check their structure
        paths = api_spec.get('paths', {})
        found_401_responses = []
        
        for path, path_obj in paths.items():
            if isinstance(path_obj, dict):
                for method, operation in path_obj.items():
                    if method in ['get', 'post', 'put', 'delete', 'patch'] and isinstance(operation, dict):
                        responses = operation.get('responses', {})
                        if '401' in responses:
                            found_401_responses.append(f"{method.upper()} {path}")
        
        # Check components for UNAUTHENTICATED error code
        components = api_spec.get('components', {})
        schemas = components.get('schemas', {})
        
        for schema_name, schema_def in schemas.items():
            if isinstance(schema_def, dict) and 'enum' in schema_def:
                enum_values = schema_def.get('enum', [])
                # Check for old pattern (should be UNAUTHENTICATED, not AUTHENTICATION_REQUIRED)
                if 'AUTHENTICATION_REQUIRED' in enum_values:
                    result.issues.append(ValidationIssue(
                        Severity.MEDIUM, "Error Codes",
                        "Use `UNAUTHENTICATED` instead of `AUTHENTICATION_REQUIRED`",
                        f"components.schemas.{schema_name}",
                        "Replace `AUTHENTICATION_REQUIRED` with `UNAUTHENTICATED`"
                    ))

    def _check_mandatory_error_responses(self, api_spec: dict, result: ValidationResult):
        """Check for mandatory error responses"""
        result.checks_performed.append("Mandatory error responses validation")
        
        paths = api_spec.get('paths', {})
        
        for path, path_obj in paths.items():
            if isinstance(path_obj, dict):
                for method, operation in path_obj.items():
                    if method in ['get', 'post', 'put', 'delete', 'patch'] and isinstance(operation, dict):
                        responses = operation.get('responses', {})
                        operation_name = f"{method.upper()} {path}"
                        
                        # Check for mandatory 400 (Bad Request)
                        if '400' not in responses:
                            result.issues.append(ValidationIssue(
                                Severity.MEDIUM, "Error Responses",
                                "Missing 400 (Bad Request) response",
                                f"{operation_name}.responses",
                                "Add 400 response for validation errors"
                            ))

    def _check_server_url_format(self, api_spec: dict, result: ValidationResult):
        """Check server URL format compliance"""
        result.checks_performed.append("Server URL format validation")
        
        servers = api_spec.get('servers', [])
        for i, server in enumerate(servers):
            if isinstance(server, dict):
                url = server.get('url', '')
                if url and not url.startswith(('{apiRoot}', 'https://')):
                    result.issues.append(ValidationIssue(
                        Severity.MEDIUM, "Server URL",
                        f"Server URL should use HTTPS or template variable: `{url}`",
                        f"servers[{i}].url",
                        "Use `{apiRoot}` template or HTTPS URL"
                    ))

    def _check_commonalities_schema_compliance(self, api_spec: dict, result: ValidationResult):
        """Check compliance with Commonalities schema requirements"""
        result.checks_performed.append("Commonalities schema compliance validation")
        
        components = api_spec.get('components', {})
        schemas = components.get('schemas', {})
        
        # Check for XCorrelator parameter consistency
        parameters = components.get('parameters', {})
        if 'X-Correlator' in parameters:
            x_correlator = parameters['X-Correlator']
            if isinstance(x_correlator, dict):
                schema = x_correlator.get('schema', {})
                pattern = schema.get('pattern')
                
                # Check for updated XCorrelator pattern in v0.6
                expected_pattern = r'^\w{8}-\w{4}-4\w{3}-[89aAbB]\w{3}-\w{12}$'
                if pattern != expected_pattern:
                    result.issues.append(ValidationIssue(
                        Severity.MEDIUM, "XCorrelator Pattern",
                        "XCorrelator pattern should follow Commonalities 0.6 specification",
                        "components.parameters.X-Correlator.schema.pattern",
                        f"Use pattern: `{expected_pattern}`"
                    ))

    def _check_event_subscription_compliance(self, api_spec: dict, result: ValidationResult):
        """Check event subscription compliance"""
        result.checks_performed.append("Event subscription compliance validation")
        
        # This check is API-type aware
        if hasattr(self, '_current_api_type'):
            api_type = self._current_api_type
        else:
            api_type = self._detect_api_type(api_spec)
        
        if api_type in [APIType.EXPLICIT_SUBSCRIPTION, APIType.IMPLICIT_SUBSCRIPTION]:
            # Check for event-related schemas
            components = api_spec.get('components', {})
            schemas = components.get('schemas', {})
            
            event_schemas_found = any('event' in name.lower() for name in schemas.keys())
            subscription_schemas_found = any('subscription' in name.lower() for name in schemas.keys())
            
            if api_type == APIType.EXPLICIT_SUBSCRIPTION and not subscription_schemas_found:
                result.issues.append(ValidationIssue(
                    Severity.MEDIUM, "Subscription Schemas",
                    "Explicit subscription API should define subscription-related schemas",
                    "components.schemas",
                    "Add schemas for subscription management"
                ))
            
            if not event_schemas_found:
                result.issues.append(ValidationIssue(
                    Severity.LOW, "Event Schemas",
                    "Subscription API should define event-related schemas",
                    "components.schemas",
                    "Consider adding event payload schemas"
                ))

    def _check_explicit_subscription_compliance(self, api_spec: dict, result: ValidationResult):
        """Check explicit subscription API compliance"""
        result.checks_performed.append("Explicit subscription API compliance validation")
        
        paths = api_spec.get('paths', {})
        subscription_paths = [path for path in paths.keys() if 'subscription' in path.lower()]
        
        if not subscription_paths:
            result.issues.append(ValidationIssue(
                Severity.CRITICAL, "Subscription Endpoints",
                "Explicit subscription API must have subscription endpoints",
                "paths",
                "Add /subscriptions endpoints for CRUD operations"
            ))
            return
        
        # Check for CRUD operations on subscription endpoints
        for path in subscription_paths:
            path_obj = paths.get(path, {})
            if isinstance(path_obj, dict):
                methods = [method for method in path_obj.keys() if method in ['get', 'post', 'put', 'delete']]
                
                if not methods:
                    result.issues.append(ValidationIssue(
                        Severity.MEDIUM, "Subscription Operations",
                        f"Subscription path `{path}` has no operations defined",
                        f"paths.{path}"
                    ))

    def _check_implicit_subscription_compliance(self, api_spec: dict, result: ValidationResult):
        """Check implicit subscription API compliance"""
        result.checks_performed.append("Implicit subscription API compliance validation")
        
        # Check for callback definitions
        paths = api_spec.get('paths', {})
        has_callbacks = False
        
        for path_obj in paths.values():
            if isinstance(path_obj, dict):
                for operation in path_obj.values():
                    if isinstance(operation, dict) and 'callbacks' in operation:
                        has_callbacks = True
                        break
        
        if not has_callbacks:
            result.issues.append(ValidationIssue(
                Severity.MEDIUM, "Implicit Subscription",
                "Implicit subscription API should define callbacks",
                "paths",
                "Add callback definitions for event notifications"
            ))

    # ===========================================
    # Project Consistency and Test Validation
    # ===========================================

    def validate_project_consistency(self, api_files: List[str]) -> ConsistencyResult:
        """Check shared schema validation across multiple API files"""
        result = ConsistencyResult()
        result.checks_performed.append("Project-wide shared schema validation")
        
        if len(api_files) < 2:
            return result
            
        # Load all API specs
        specs = {}
        for api_file in api_files:
            try:
                with open(api_file, 'r', encoding='utf-8') as f:
                    specs[api_file] = yaml.safe_load(f)
            except Exception as e:
                result.issues.append(ValidationIssue(
                    Severity.CRITICAL, "File Loading",
                    f"Failed to load `{api_file}`: {str(e)}",
                    api_file
                ))
                continue
        
        if len(specs) < 2:
            return result
            
        # Define common schemas that should be identical
        common_schema_names = [
            'XCorrelator', 'ErrorInfo', 'Device', 'DeviceResponse', 
            'PhoneNumber', 'NetworkAccessIdentifier', 'DeviceIpv4Addr', 
            'DeviceIpv6Address', 'SingleIpv4Addr', 'Port', 'Point', 
            'Latitude', 'Longitude', 'Area', 'AreaType', 'Circle'
        ]
        
        # Check each common schema
        for schema_name in common_schema_names:
            self._validate_shared_schema(schema_name, specs, result)
        
        # Check license consistency
        self._validate_license_consistency(specs, result)
        
        # Check commonalities version consistency
        self._validate_commonalities_consistency(specs, result)
        
        return result

    def _validate_shared_schema(self, schema_name: str, specs: dict, result: ConsistencyResult):
        """Validate that a shared schema is consistent across files"""
        schemas_found = {}
        
        for file_path, spec in specs.items():
            components = spec.get('components', {})
            schemas = components.get('schemas', {})
            if schema_name in schemas:
                schemas_found[file_path] = schemas[schema_name]
        
        if len(schemas_found) < 2:
            return
            
        # Compare schemas (allowing for differences in examples and descriptions)
        file_paths = list(schemas_found.keys())
        reference_file = file_paths[0]
        reference_schema = self._normalize_schema_for_comparison(schemas_found[reference_file])
        
        for file_path in file_paths[1:]:
            current_schema = self._normalize_schema_for_comparison(schemas_found[file_path])
            
            if current_schema != reference_schema:
                result.issues.append(ValidationIssue(
                    Severity.MEDIUM, "Schema Consistency",
                    f"Schema `{schema_name}` differs between files",
                    f"{Path(reference_file).name} vs {Path(file_path).name}",
                    f"Ensure `{schema_name}` schema is identical across all files"
                ))

    def _normalize_schema_for_comparison(self, schema: Any) -> Any:
        """Normalize schema for comparison by removing examples and descriptions"""
        if isinstance(schema, dict):
            normalized = {}
            for key, value in schema.items():
                if key not in ['example', 'examples', 'description']:
                    normalized[key] = self._normalize_schema_for_comparison(value)
            return normalized
        elif isinstance(schema, list):
            return [self._normalize_schema_for_comparison(item) for item in schema]
        else:
            return schema

    def _validate_license_consistency(self, specs: dict, result: ConsistencyResult):
        """Check that license information is consistent"""
        licenses = {}
        
        for file_path, spec in specs.items():
            license_info = spec.get('info', {}).get('license', {})
            if license_info:
                licenses[file_path] = license_info
        
        if len(licenses) < 2:
            return
            
        reference_file = list(licenses.keys())[0]
        reference_license = licenses[reference_file]
        
        for file_path, license_info in licenses.items():
            if file_path == reference_file:
                continue
                
            if license_info != reference_license:
                result.issues.append(ValidationIssue(
                    Severity.MEDIUM, "License Consistency",
                    "License information differs between files",
                    f"{Path(reference_file).name} vs {Path(file_path).name}",
                    "Ensure all files have identical license information"
                ))

    def _validate_commonalities_consistency(self, specs: dict, result: ConsistencyResult):
        """Check that commonalities version is consistent"""
        versions = {}
        
        for file_path, spec in specs.items():
            version = spec.get('info', {}).get('x-camara-commonalities')
            if version:
                versions[file_path] = str(version)
        
        if len(versions) < 2:
            return
            
        reference_file = list(versions.keys())[0]
        reference_version = versions[reference_file]
        
        for file_path, version in versions.items():
            if file_path == reference_file:
                continue
                
            if version != reference_version:
                result.issues.append(ValidationIssue(
                    Severity.MEDIUM, "Commonalities Consistency",
                    f"Commonalities version differs: `{reference_version}` vs `{version}`",
                    f"{Path(reference_file).name} vs {Path(file_path).name}",
                    "Ensure all files use the same commonalities version"
                ))

    def map_and_validate_test_files_to_apis(self, api_files: List[str], test_dir: str) -> List[TestAlignmentResult]:
        """Map test files to APIs and validate each pair"""
        test_results = []
        
        # Extract all API names first
        all_api_names = []
        for api_file in api_files:
            try:
                with open(api_file, 'r', encoding='utf-8') as f:
                    api_spec = yaml.safe_load(f)
                
                # Extract api-name from servers URL
                api_name = self._extract_api_name_from_servers(api_spec)
                
                # Fallback to filename if servers extraction fails
                if not api_name:
                    api_name = Path(api_file).stem
                
                all_api_names.append(api_name)
            except Exception:
                # If we can't load the API file, use filename as fallback
                all_api_names.append(Path(api_file).stem)
        
        # Find all test files
        test_path = Path(test_dir)
        if not test_path.exists():
            # No test directory - create empty results for each API
            for api_file in api_files:
                result = TestAlignmentResult(api_file=api_file)
                result.checks_performed.append("Test alignment validation")
                result.issues.append(ValidationIssue(
                    Severity.CRITICAL, "Test Directory",
                    f"Test directory does not exist: {test_dir}",
                    test_dir
                ))
                test_results.append(result)
            return test_results
        
        all_test_files = [f.stem for f in test_path.glob("*.feature")]
        
        # Simple assignment logic: test_file_stem -> api_name
        test_file_assignments = {}
        
        for api_name in all_api_names:
            for test_file_stem in all_test_files:
                # Check for match (exact or prefix)
                is_exact_match = (test_file_stem == api_name)
                is_prefix_match = test_file_stem.startswith(f"{api_name}-")
                
                if is_exact_match or is_prefix_match:
                    current_assignment = test_file_assignments.get(test_file_stem)
                    
                    if current_assignment is None:
                        # No assignment yet - assign it
                        test_file_assignments[test_file_stem] = api_name
                    elif len(api_name) > len(current_assignment):
                        # Longer prefix wins - reassign
                        test_file_assignments[test_file_stem] = api_name
        
        # Create reverse mapping: api_name -> [test_file_paths]
        api_to_test_files = {api_name: [] for api_name in all_api_names}
        for test_file_stem, api_name in test_file_assignments.items():
            test_file_path = str(test_path / f"{test_file_stem}.feature")
            api_to_test_files[api_name].append(test_file_path)
        
        # Find orphan test files
        orphan_test_files = []
        for test_file_stem in all_test_files:
            if test_file_stem not in test_file_assignments:
                orphan_test_files.append(f"{test_file_stem}.feature")
        
        # Validate each API with its assigned test files
        for api_file in api_files:
            api_name = all_api_names[api_files.index(api_file)]
            assigned_test_files = api_to_test_files[api_name]
            
            result = self.validate_test_alignment_single(api_file, api_name, assigned_test_files)
            test_results.append(result)
        
        # Report orphan test files as issues in the first API result
        if orphan_test_files and test_results:
            for orphan_file in orphan_test_files:
                test_results[0].issues.append(ValidationIssue(
                    Severity.MEDIUM, "Orphan Test Files",
                    f"Test file `{orphan_file}` does not match any API",
                    f"{test_dir}/{orphan_file}",
                    f"Rename to match an API: {', '.join(all_api_names)}"
                ))
        
        return test_results

    def validate_test_alignment_single(self, api_file: str, api_name: str, assigned_test_files: List[str]) -> TestAlignmentResult:
        """Validate test alignment for a single API with its assigned test files"""
        result = TestAlignmentResult(api_file=api_file)
        result.test_files = assigned_test_files
        result.checks_performed.append("Test alignment validation")
        
        # Load API spec
        try:
            with open(api_file, 'r', encoding='utf-8') as f:
                api_spec = yaml.safe_load(f)
        except Exception as e:
            result.issues.append(ValidationIssue(
                Severity.CRITICAL, "API Loading",
                f"Failed to load API file: {str(e)}",
                api_file
            ))
            return result
        
        # Extract API info
        api_info = api_spec.get('info', {})
        api_version = api_info.get('version', '')
        api_title = api_info.get('title', '')
        
        if not assigned_test_files:
            result.issues.append(ValidationIssue(
                Severity.CRITICAL, "Test Files",
                f"No test files found for API `{api_name}`",
                "test directory",
                f"Create either `{api_name}.feature` or `{api_name}-<operationId>.feature` files"
            ))
            return result
        
        # Extract operation IDs from API
        api_operations = self._extract_operation_ids(api_spec)
        
        # Validate each assigned test file
        for test_file in assigned_test_files:
            self._validate_test_file(test_file, api_name, api_version, api_title, 
                                api_operations, result)
        
        return result

    def _extract_operation_ids(self, api_spec: dict) -> List[str]:
        """Extract all operation IDs from API spec"""
        operation_ids = []
        
        paths = api_spec.get('paths', {})
        for path, path_obj in paths.items():
            for method, operation in path_obj.items():
                if method in ['get', 'post', 'put', 'delete', 'patch']:
                    operation_id = operation.get('operationId')
                    if operation_id:
                        operation_ids.append(operation_id)
        
        return operation_ids

    def _validate_test_file(self, test_file: str, api_name: str, api_version: str, 
                           api_title: str, api_operations: List[str], result: TestAlignmentResult):
        """Validate individual test file"""
        try:
            with open(test_file, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception as e:
            result.issues.append(ValidationIssue(
                Severity.CRITICAL, "Test File Loading",
                f"Failed to load test file: {str(e)}",
                test_file
            ))
            return
        
        lines = content.split('\n')
    
        # Validate URLs in test files match expected API name and version format
        self._validate_test_file_urls(content, api_name, api_version, test_file, result)
        
        # Check for version in Feature line (can be line 1 or 2)
        feature_line = None
        feature_line_number = None
        
        # Check first two lines for Feature line
        for i, line in enumerate(lines[:2]):
            stripped_line = line.strip()
            if stripped_line.startswith('Feature:'):
                feature_line = stripped_line
                feature_line_number = i + 1
                break
        
        if feature_line:
            if not self._validate_test_version_line(feature_line, api_version, api_title):
                result.issues.append(ValidationIssue(
                    Severity.MEDIUM, "Test Version",
                    f"Feature line doesn't mention API version `{api_version}`",
                    f"{test_file}:line {feature_line_number}",
                    f"Include version `{api_version}` in Feature line: {feature_line}"
                ))
        else:
            result.issues.append(ValidationIssue(
                Severity.MEDIUM, "Test Structure",
                "No Feature line found in first two lines",
                f"{test_file}:lines 1-2",
                "Add Feature line with API name and version"
            ))
        
        # Check operation IDs referenced in test
        test_operations = self._extract_test_operations(content)
        
        # Validate that test operations exist in API
        for test_op in test_operations:
            if test_op not in api_operations:
                result.issues.append(ValidationIssue(
                    Severity.CRITICAL, "Test Operation IDs",
                    f"Test references unknown operation `{test_op}`",
                    test_file,
                    f"Use valid operation ID from: `{', '.join(api_operations)}`"
                ))
        
        # For operation-specific test files, validate naming
        test_filename = Path(test_file).stem
        if test_filename.startswith(f"{api_name}-"):
            expected_operation = test_filename.replace(f"{api_name}-", "")
            if expected_operation not in api_operations:
                result.issues.append(ValidationIssue(
                    Severity.LOW, "Test File Naming",
                    f"Test file suggests operation `{expected_operation}` but it doesn't exist in API",
                    test_file,
                    f"Check if test file naming is as intended, consider to use valid operation from: `{', '.join(api_operations)}`"
                ))

    def _validate_test_file_urls(self, content: str, api_name: str, api_version: str, test_file: str, result: TestAlignmentResult):
        """Validate that URLs in test files match the expected API name and version format"""
        
        # Find URLs in test content (looking for patterns like /api-name/version/endpoint)
        # Common patterns: 
        #   And the resource "/brand-registration/v0.1rc1/registrations"
        #   And the resource "qos-profiles/vwip/retrieve-qos-profiles"
        #   Given the resource "{apiroot}/geofencing-subscriptions/v0.5rc1/"
        # Regex pattern explanation:
        #   - (?:\{[^}]+\}/)? - optional template variable like {apiRoot}/ or {apiroot}/
        #   - /? - optional leading slash
        #   - ([a-zA-Z0-9_-]+) - captures API name
        #   - \/ - literal slash
        #   - (vwip|wip|v\d+...) - captures version
        #   - (\/[^"\']*)?  - optionally captures rest of path
        # Captures: (api-name, version, rest-of-path)
        url_pattern = r'["\'](?:\{[^}]+\}/)?/?([a-zA-Z0-9_-]+)\/(vwip|wip|v\d+(?:\.\d+)?(?:rc\d+|alpha\d+)?)(\/[^"\']*)?["\']'
        matches = re.findall(url_pattern, content)
        
        if not matches:
            # No URLs found - this is a critical error for API test files
            result.issues.append(ValidationIssue(
                Severity.CRITICAL, "Test URLs",
                "No API resource URLs found in test file",
                test_file,
                f'Add resource URLs like: And the resource "/{api_name}/<version>/endpoint" or "{{apiRoot}}/{api_name}/<version>/endpoint"'
            ))
            return
        
        # Also check for URLs without leading slash (for style recommendation)
        # This pattern specifically looks for URLs without template variables and without leading slash
        # We don't flag URLs with template variables as they're typically root-relative already
        no_slash_pattern = r'["\'](?!\{[^}]+\}/)([a-zA-Z0-9_-]+\/(vwip|wip|v\d+(?:\.\d+)?(?:rc\d+|alpha\d+)?)(?:\/[^"\']*)?)["\']'
        no_slash_matches = re.findall(no_slash_pattern, content)
        
        # Process matches - each match is (api_name_part, version_part, rest_of_path)
        found_urls = [(match[0], match[1], match[2] if len(match) > 2 else '') for match in matches]
        
        # Get expected URL suffix using the helper function
        expected_suffix = self._get_expected_url_suffix(api_version)
        
        # Check each found URL
        for url_api_name, url_version, rest_of_path in found_urls:
            full_url = f"/{url_api_name}/{url_version}{rest_of_path}"
            
            # First check API name consistency
            if url_api_name != api_name:
                result.issues.append(ValidationIssue(
                    Severity.CRITICAL, "Test URLs",
                    f"Test file uses incorrect API name `{url_api_name}` (should be `{api_name}`)",
                    f"{test_file}: URL '{full_url}'",
                    f"Update to use correct API name: `{api_name}`"
                ))
            
            # Then check version suffix - but only if API name is correct and we have a valid expected suffix
            elif expected_suffix and url_version == 'wip':
                result.issues.append(ValidationIssue(
                    Severity.CRITICAL, "Test URLs",
                    f"Test file uses invalid `/wip` suffix",
                    f"{test_file}: URL '{full_url}'",
                    f"Update to use `{expected_suffix}`"
                ))
            elif expected_suffix and api_version != 'wip' and url_version == 'vwip':
                result.issues.append(ValidationIssue(
                    Severity.CRITICAL, "Test URLs",
                    f"Test file uses work-in-progress URL suffix `/vwip` for version `{api_version}`",
                    f"{test_file}: URL '{full_url}'",
                    f"Update to use `{expected_suffix}`"
                ))
            elif expected_suffix and url_version != expected_suffix.lstrip('/'):
                result.issues.append(ValidationIssue(
                    Severity.MEDIUM, "Test URLs",
                    f"Test file URL version `/{url_version}` doesn't match API version `{api_version}`",
                    f"{test_file}: URL '{full_url}'",
                    f"Expected: `{expected_suffix}`"
                ))
        
        # Report URLs without leading slash as low priority style issue
        if no_slash_matches:
            for url_match in no_slash_matches:
                url_str = url_match[0] if isinstance(url_match, tuple) else url_match
                result.issues.append(ValidationIssue(
                    Severity.LOW, "Test URL Style",
                    f"Resource URL without leading slash: `\"{url_str}\"`",
                    test_file,
                    f"Consider using root-relative path with leading slash: `\"/{url_str}\"`"
                ))

    def _validate_test_version_line(self, feature_line: str, api_version: str, api_title: str) -> bool:
        """Check if Feature line contains the API version"""
        # Special handling for WIP versions - accept both 'wip' and 'vwip'
        if api_version == 'wip':
            feature_lower = feature_line.lower()
            return 'wip' in feature_lower or 'vwip' in feature_lower
        
        # Look for semantic version pattern in Feature line
        version_pattern = r'v?\d+\.\d+\.\d+(?:-rc\.\d+|-alpha\.\d+)?'
        found_versions = re.findall(version_pattern, feature_line)
        
        # Check for both exact version and version with 'v' prefix
        return api_version in found_versions or f'v{api_version}' in found_versions

    def _extract_test_operations(self, content: str) -> List[str]:
        """Extract operation IDs referenced in test content"""
        # Look for patterns like 'request "operationId"'
        operation_pattern = r'request\s+"([^"]+)"'
        operations = re.findall(operation_pattern, content)
        
        return list(set(operations))  # Remove duplicates


def find_api_files(directory: str) -> List[str]:
    """Find all YAML files in the API definitions directory"""
    api_dir = Path(directory) / "code" / "API_definitions"
    
    if not api_dir.exists():
        return []
    
    yaml_files = []
    for pattern in ['*.yaml', '*.yml']:
        yaml_files.extend(api_dir.glob(pattern))
    
    return [str(f) for f in yaml_files]

def generate_report(results: List[ValidationResult], output_dir: str, repo_name: str = "", issue_number: str = "", 
                   consistency_result: Optional[ConsistencyResult] = None, 
                   test_results: List[TestAlignmentResult] = None, commonalities_version: str = "0.6"):
    """Generate comprehensive report and summary with API type detection"""
    os.makedirs(output_dir, exist_ok=True)
    
    # Generate unique filename with repository name and timestamp
    timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    
    # Clean version for filename (remove dots)
    version_clean = commonalities_version.replace('.', '_')
    
    if repo_name and issue_number and issue_number != "0":
        base_filename = f"api_review_{repo_name}_comment{issue_number}_v{version_clean}_{timestamp}"
    elif repo_name:
        base_filename = f"api_review_{repo_name}_manual_v{version_clean}_{timestamp}"
    else:
        base_filename = f"api_review_v{version_clean}_{timestamp}"

    report_filename = safe_filename(f"{base_filename}.md")
    
    # Calculate totals
    total_critical = sum(r.critical_count for r in results)
    total_medium = sum(r.medium_count for r in results)
    total_low = sum(r.low_count for r in results)
    
    if consistency_result:
        total_critical += len([i for i in consistency_result.issues if i.severity == Severity.CRITICAL])
        total_medium += len([i for i in consistency_result.issues if i.severity == Severity.MEDIUM])
        total_low += len([i for i in consistency_result.issues if i.severity == Severity.LOW])
    
    if test_results:
        for test_result in test_results:
            total_critical += len([i for i in test_result.issues if i.severity == Severity.CRITICAL])
            total_medium += len([i for i in test_result.issues if i.severity == Severity.MEDIUM])
            total_low += len([i for i in test_result.issues if i.severity == Severity.LOW])
    
    # Collect all checks performed and manual checks needed
    all_checks_performed = set()
    all_manual_checks = set()
    
    for result in results:
        all_checks_performed.update(result.checks_performed)
        all_manual_checks.update(result.manual_checks_needed)
    
    if consistency_result:
        all_checks_performed.update(consistency_result.checks_performed)
    
    if test_results:
        for test_result in test_results:
            all_checks_performed.update(test_result.checks_performed)
    
    # Generate detailed report
    with open(f"{output_dir}/{report_filename}", "w") as f:
        f.write(f"# CAMARA API Review Report\n\n")
        if repo_name:
            f.write(f"**Repository**: {repo_name}\n")
        if issue_number and issue_number != "0":
            f.write(f"**Issue/PR**: #{issue_number}\n")
        f.write(f"**Generated**: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} UTC\n")
        f.write(f"**Requested Commonalities Version**: {commonalities_version}\n")
        f.write(f"**Validator Implementation**: v0.6\n")
        
        # Add version warning if mismatch
        if commonalities_version != "0.6":
            f.write(f"\n> ⚠️ **Note**: This validator implements Commonalities v0.6 compliance rules. ")
            f.write(f"The requested version {commonalities_version} validation is performed using v0.6 rules.\n")
        
        f.write("\n---\n\n")

    # Generate detailed report
    with open(f"{output_dir}/{report_filename}", "w") as f:
        f.write(f"# CAMARA API Review Report\n\n")
        f.write(f"**Generated**: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"**Commonalities Version**: {commonalities_version}\n")
        
        if repo_name:
            f.write(f"**Repository**: {repo_name}\n")
        if issue_number:
            f.write(f"**Issue or PR Number**: {issue_number}\n")
        
        f.write(f"\n## Executive Summary\n\n")
        f.write(f"- **APIs Reviewed**: {len(results)}\n")
        f.write(f"- **Critical Issues**: {total_critical}\n")
        f.write(f"- **Medium Issues**: {total_medium}\n")
        f.write(f"- **Low Issues**: {total_low}\n")
        f.write(f"- **Multi-file Consistency**: {'✅ Checked' if consistency_result else '⏭️ Skipped (single file)'}\n")
        f.write(f"- **Test Alignment**: {'✅ Checked' if test_results else '⏭️ Skipped (no tests found)'}\n\n")
        
        # API Type Summary
        type_counts = {}
        for result in results:
            api_type = result.api_type.value
            type_counts[api_type] = type_counts.get(api_type, 0) + 1
        
        if type_counts:
            f.write("### API Types Detected\n\n")
            for api_type, count in type_counts.items():
                f.write(f"- **{api_type}**: {count}\n")
            f.write("\n")
        
        # 1. INDIVIDUAL API RESULTS
        f.write("## Individual API Analysis\n\n")
        for result in results:
            f.write(f"### `{result.api_name}` v{result.version}\n\n")
            f.write(f"**File**: `{Path(result.file_path).name}`\n")
            f.write(f"**Type**: {result.api_type.value}\n")
            f.write(f"**Issues**: {result.critical_count} critical, {result.medium_count} medium, {result.low_count} low\n\n")
            
            if result.issues:
                f.write("#### Issues Found\n\n")
                for issue in result.issues:
                    f.write(f"**{issue.severity.value}**: {issue.category}\n")
                    f.write(f"- **Description**: {sanitize_report_content(issue.description)}\n")
                    if issue.location:
                        f.write(f"- **Location**: `{issue.location}`\n")
                    if issue.fix_suggestion:
                        f.write(f"- **Fix**: {sanitize_report_content(issue.fix_suggestion)}\n")
                    f.write("\n")
            else:
                f.write("✅ **No issues found**\n\n")
        
        # 2. PROJECT CONSISTENCY RESULTS
        if consistency_result and consistency_result.issues:
            f.write("## Project-Wide Consistency Issues\n\n")
            for issue in consistency_result.issues:
                f.write(f"**{issue.severity.value}**: {issue.category}\n")
                f.write(f"- **Description**: {sanitize_report_content(issue.description)}\n")
                if issue.location:
                    f.write(f"- **Location**: `{issue.location}`\n")
                if issue.fix_suggestion:
                    f.write(f"- **Fix**: {sanitize_report_content(issue.fix_suggestion)}\n")
                f.write("\n")
        
        # 3. TEST ALIGNMENT RESULTS
        if test_results:
            f.write("## Test Alignment Analysis\n\n")
            for test_result in test_results:
                api_name = Path(test_result.api_file).stem
                f.write(f"### Tests for `{api_name}`\n\n")
                
                if test_result.test_files:
                    f.write("**Test Files Found**:\n")
                    for test_file in test_result.test_files:
                        f.write(f"- `{Path(test_file).name}`\n")
                    f.write("\n")
                else:
                    f.write("❌ **No test files found**\n\n")
                
                if test_result.issues:
                    f.write("#### Test Issues\n\n")
                    for issue in test_result.issues:
                        f.write(f"**{issue.severity.value}**: {issue.category}\n")
                        f.write(f"- **Description**: {sanitize_report_content(issue.description)}\n")
                        if issue.location:
                            f.write(f"- **Location**: `{issue.location}`\n")
                        if issue.fix_suggestion:
                            f.write(f"- **Fix**: {sanitize_report_content(issue.fix_suggestion)}\n")
                        f.write("\n")
        
        # 4. CRITICAL ISSUES SUMMARY  
        critical_issues = []
        for result in results:
            critical_issues.extend([i for i in result.issues if i.severity == Severity.CRITICAL])
        
        if consistency_result:
            critical_issues.extend([i for i in consistency_result.issues if i.severity == Severity.CRITICAL])
        
        if test_results:
            for test_result in test_results:
                critical_issues.extend([i for i in test_result.issues if i.severity == Severity.CRITICAL])
        
        if critical_issues:
            f.write("## Critical Issues Requiring Immediate Attention\n\n")
            for issue in critical_issues[:10]:  # Limit to first 10
                f.write(f"- **{issue.category}**: {sanitize_report_content(issue.description)}")
                if issue.location:
                    f.write(f" (`{issue.location}`)")
                f.write("\n")
            
            if len(critical_issues) > 10:
                f.write(f"\n*... and {len(critical_issues) - 10} more critical issues. See detailed report for complete analysis.*\n")
            
            f.write("\n")
        
        # 5. AUTOMATED CHECKS PERFORMED
        if all_checks_performed:
            f.write("## Automated Checks Performed\n\n")
            for check in sorted(all_checks_performed):
                f.write(f"- {check}\n")
            f.write("\n")
        
        # 6. MANUAL REVIEW REQUIRED
        if all_manual_checks:
            f.write("## Manual Review Required\n\n")
            for check in sorted(all_manual_checks):
                f.write(f"- {check}\n")
            f.write("\n")
        
    # Generate summary for GitHub comment with 25-item limit
    with open(f"{output_dir}/summary.md", "w") as f:
        if not results:
            f.write("❌ **No API definition files found**\n\n")
            f.write("Please ensure YAML files are located in `/code/API_definitions/`\n")
            return report_filename

        # No need for special sanitization - just ensure single lines
        def sanitize_for_summary(text: str) -> str:
            """Ensure text is on a single line"""
            # Replace all whitespace (including newlines) with single spaces
            return ' '.join(text.split())        
   
        # Overall status
        if total_critical == 0:
            if total_medium == 0:
                status = "✅ **Ready for Release**"
            else:
                status = "⚠️ **Conditional Approval**"
        else:
            status = "❌ **Critical Issues Found**"
        
        f.write(f"### {status}\n\n")
        
        # APIs found with types
        f.write("**APIs Reviewed**:\n")
        for result in results:
            type_indicator = {
                APIType.EXPLICIT_SUBSCRIPTION: "🔔",
                APIType.IMPLICIT_SUBSCRIPTION: "📧", 
                APIType.REGULAR: "📄"
            }.get(result.api_type, "📄")
            
            f.write(f"- {type_indicator} `{result.api_name}` v{result.version} ({result.api_type.value})\n")
        f.write("\n")
        
        # Issue summary
        f.write("**Issues Summary**:\n")
        f.write(f"- 🔴 Critical: {total_critical}\n")
        f.write(f"- 🟡 Medium: {total_medium}\n")
        f.write(f"- 🔵 Low: {total_low}\n\n")
        
        # Enhanced issues detail with 25-item limit, prioritizing critical then medium
        if total_critical > 0 or total_medium > 0:
            f.write("**Issues Requiring Attention**:\n")
            
            # Collect all issues from all sources
            all_critical_issues = []
            all_medium_issues = []
            
            # From individual API results
            for result in results:
                critical_issues = [i for i in result.issues if i.severity == Severity.CRITICAL]
                medium_issues = [i for i in result.issues if i.severity == Severity.MEDIUM]
                
                for issue in critical_issues:
                    all_critical_issues.append((result.api_name, issue))
                for issue in medium_issues:
                    all_medium_issues.append((result.api_name, issue))
            
            # From consistency results
            if consistency_result:
                critical_issues = [i for i in consistency_result.issues if i.severity == Severity.CRITICAL]
                medium_issues = [i for i in consistency_result.issues if i.severity == Severity.MEDIUM]
                
                for issue in critical_issues:
                    all_critical_issues.append(("Project-wide", issue))
                for issue in medium_issues:
                    all_medium_issues.append(("Project-wide", issue))
            
            # From test results
            if test_results:
                for test_result in test_results:
                    critical_issues = [i for i in test_result.issues if i.severity == Severity.CRITICAL]
                    medium_issues = [i for i in test_result.issues if i.severity == Severity.MEDIUM]
                    
                    api_name = Path(test_result.api_file).stem
                    for issue in critical_issues:
                        all_critical_issues.append((f"{api_name} Tests", issue))
                    for issue in medium_issues:
                        all_medium_issues.append((f"{api_name} Tests", issue))
            
            # Show critical issues first (up to 20 to leave room for medium)
            critical_to_show = min(len(all_critical_issues), 20)
            
            if critical_to_show > 0:
                f.write(f"\n**🔴 Critical Issues ({critical_to_show}):**\n")
                for source_name, issue in all_critical_issues[:critical_to_show]:
                    description = sanitize_for_summary(issue.description)
                    f.write(f"- *{source_name}*: **{issue.category}** - {description}\n")
            
            # Show medium issues if there's room
            remaining_slots = 25 - critical_to_show
            medium_to_show = min(len(all_medium_issues), remaining_slots)
            
            if medium_to_show > 0:
                f.write(f"\n**🟡 Medium Priority Issues ({medium_to_show}):**\n")
                for source_name, issue in all_medium_issues[:medium_to_show]:
                    description = sanitize_for_summary(issue.description)
                    f.write(f"- *{source_name}*: **{issue.category}** - {description}\n")
            
            # Note if there are more issues not shown
            total_not_shown = (len(all_critical_issues) + len(all_medium_issues)) - 25
            if total_not_shown > 0:
                f.write(f"\n*Note: {total_not_shown} additional issues not shown above. See detailed report for complete analysis.*\n")
            
            f.write("\n")
        
        # Recommendation
        if total_critical == 0 and total_medium == 0:
            f.write("**Recommendation**: ✅ Approved for release\n")
        elif total_critical == 0:
            f.write("**Recommendation**: ⚠️ Approved with medium-priority improvements recommended\n")
        else:
            f.write(f"**Recommendation**: ❌ Address {total_critical} critical issue(s) before release\n")
        
        f.write(f"\n📄 **Detailed Report**: {report_filename}\n")
        f.write("\n📄 **Download**: Available as workflow artifact for complete analysis\n")
        f.write("\n🔍 **Validation**: This review includes subscription type detection, scope validation, filename consistency, schema compliance, project consistency, and test alignment validation\n")
    
    # Return the report filename for use by the workflow
    return report_filename

def main():
    """Main function with modern argparse structure matching workflow expectations"""
    print("🔍 Debug: Python script starting...")
    print(f"🔍 Debug: Command line args: {sys.argv}")
    print(f"🔍 Debug: Python version: {sys.version}")
    
    # Modern argparse structure that matches the workflow
    parser = argparse.ArgumentParser(description='CAMARA API Review Validator v0.6')
    parser.add_argument('repo_path', help='Path to repository containing API definitions')
    parser.add_argument('--output', required=True, help='Output directory for reports')
    parser.add_argument('--repo-name', required=True, help='Repository name')
    parser.add_argument('--issue-number', required=False, default='0', help='Issue or PR number for context')
    parser.add_argument('--commonalities-version', required=True, help='CAMARA Commonalities version')
    parser.add_argument('--review-type', required=True, help='Type of review (release-candidate, wip, public-release)')
    parser.add_argument('--verbose', action='store_true', help='Enable verbose logging')
    
    print("🔍 Debug: Argument parser created successfully")
    
    # Parse arguments with explicit error handling
    try:
        print("🔍 Debug: About to parse arguments...")
        args = parser.parse_args()
        print("🔍 Debug: Arguments parsed successfully!")
        
        # Print all parsed arguments for debugging
        print("🔍 Debug: Parsed arguments:")
        print(f"  repo_path: '{args.repo_path}'")
        print(f"  output: '{args.output}'")
        print(f"  repo_name: '{args.repo_name}'")
        print(f"  issue_number: '{args.issue_number}'")
        print(f"  commonalities_version: '{args.commonalities_version}'")
        print(f"  review_type: '{args.review_type}'")
        print(f"  verbose: {args.verbose}")
        
    except SystemExit as e:
        print(f"❌ SystemExit during argument parsing: {e}")
        print("❌ This usually means argument parsing failed")
        parser.print_help()
        sys.exit(1)
    except Exception as e:
        print(f"❌ Unexpected error during argument parsing: {e}")
        print(f"❌ Error type: {type(e).__name__}")
        traceback.print_exc()
        sys.exit(1)
    
    # Validate and sanitize inputs
    try:
        print("🔍 Debug: Starting input validation...")
        
        repo_dir = validate_directory_path(args.repo_path)
        print(f"🔍 Debug: Repository directory validated: {repo_dir}")
        
        # Get and validate commonalities version
        commonalities_version = str(args.commonalities_version).strip()
        print(f"🔍 Debug: Commonalities version: '{commonalities_version}'")
        
        # Validate commonalities version format
        if not re.match(r'^\d+\.\d+$', commonalities_version):
            print(f"❌ Invalid commonalities version format: '{commonalities_version}'")
            raise ValueError(f"Invalid commonalities version format: {commonalities_version}. Expected format: X.Y (e.g., 0.6)")
        
        print(f"✅ Debug: Commonalities version validation passed: {commonalities_version}")
        
        output_dir = args.output
        repo_name = re.sub(r'[^a-zA-Z0-9_-]', '', args.repo_name)[:100]
        issue_number = re.sub(r'[^0-9]', '', args.issue_number)[:20]
        
        # Create output directory
        abs_output_dir = os.path.abspath(os.path.expanduser(output_dir))
        if not os.path.exists(abs_output_dir):
            print(f"🔍 Debug: Creating output directory: {abs_output_dir}")
            os.makedirs(abs_output_dir, mode=0o755)
        
        print("✅ Debug: All input validation passed!")
        
    except ValueError as e:
        print(f"❌ Input validation error: {str(e)}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Unexpected error during validation: {str(e)}")
        traceback.print_exc()
        sys.exit(1)
    
    if args.verbose:
        print(f"🚀 Starting CAMARA API validation (Commonalities {commonalities_version})")
        print(f"📁 Repository directory: {repo_dir}")
        print(f"📊 Output directory: {output_dir}")
        print(f"📦 Repository: {repo_name}")
        print(f"🔗 PR Number: {issue_number}")
        print(f"🔧 Review Type: {args.review_type}")
    
    # Find API files
    api_files = find_api_files(repo_dir)
    
    if not api_files:
        print("❌ No API definition files found")
        print(f"Checked location: {repo_dir}/code/API_definitions/")
        print("📄 Creating empty results report...")
        try:
            report_filename = generate_report([], output_dir, repo_name, issue_number, commonalities_version=commonalities_version)
            print(f"📄 Empty report generated: {report_filename}")
        except Exception as e:
            print(f"❌ Error generating empty report: {str(e)}")
        sys.exit(0)
    
    if args.verbose:
        print(f"🔍 Found {len(api_files)} API definition file(s)")
        for file in api_files:
            print(f"  - {file}")
    
    # Validate each file
    validator = CAMARAAPIValidator(commonalities_version, args.review_type)
    results = []
    
    for api_file in api_files:
        if args.verbose:
            print(f"\n📋 Validating {api_file}...")
        try:
            result = validator.validate_api_file(api_file)
            results.append(result)
            
            if args.verbose:
                print(f"  📄 API Type: {result.api_type.value}")
                print(f"  🔴 Critical: {result.critical_count}")
                print(f"  🟡 Medium: {result.medium_count}")
                print(f"  🔵 Low: {result.low_count}")
                
        except Exception as e:
            print(f"  ❌ Error validating {api_file}: {str(e)}")
            # Create error result
            error_result = ValidationResult(file_path=api_file)
            error_result.issues.append(ValidationIssue(
                Severity.CRITICAL, "Validation Error", f"Failed to validate file: {str(e)}"
            ))
            results.append(error_result)
    
    # Project-wide consistency validation
    consistency_result = None
    if len(api_files) > 1:
        if args.verbose:
            print(f"\n🔗 Performing project consistency validation...")
        try:
            consistency_result = validator.validate_project_consistency(api_files)
            consistency_critical = len([i for i in consistency_result.issues if i.severity == Severity.CRITICAL])
            consistency_medium = len([i for i in consistency_result.issues if i.severity == Severity.MEDIUM])
            consistency_low = len([i for i in consistency_result.issues if i.severity == Severity.LOW])
            
            if args.verbose:
                print(f"  🔴 Critical: {consistency_critical}")
                print(f"  🟡 Medium: {consistency_medium}")
                print(f"  🔵 Low: {consistency_low}")
        except Exception as e:
            print(f"  ❌ Error in consistency validation: {str(e)}")
    
    # Test alignment validation
    test_results = []
    test_dir = os.path.join(repo_dir, "code", "Test_definitions")
    if os.path.exists(test_dir):
        if args.verbose:
            print(f"\n🧪 Performing test alignment validation...")
        try:
            # Use the simplified two-level validation approach
            test_results = validator.map_and_validate_test_files_to_apis(api_files, test_dir)
            
            if args.verbose:
                for test_result in test_results:
                    api_name = Path(test_result.api_file).stem
                    test_critical = len([i for i in test_result.issues if i.severity == Severity.CRITICAL])
                    test_medium = len([i for i in test_result.issues if i.severity == Severity.MEDIUM])
                    test_low = len([i for i in test_result.issues if i.severity == Severity.LOW])
                    print(f"  📋 {api_name}: {len(test_result.test_files)} test files, {test_critical} critical, {test_medium} medium, {test_low} low")
        except Exception as e:
            print(f"  ❌ Error in test validation: {str(e)}")
    
    # Generate reports
    try:
        report_filename = generate_report(results, output_dir, repo_name, issue_number, 
                                        consistency_result, test_results, commonalities_version=commonalities_version)
        print(f"📄 Report generated: {report_filename}")
    except Exception as e:
        print(f"❌ Error generating report: {str(e)}")
        traceback.print_exc()
        
        # Try to create a fallback summary
        try:
            with open(f"{output_dir}/summary.md", "w") as f:
                f.write("❌ **Report Generation Failed**\n\n")
                f.write(f"Error: {str(e)}\n\n")
                f.write("Please check the workflow logs for details.\n")

            print("📄 Fallback summary report created")
        except Exception as fallback_error:
            print(f"❌ Even fallback report failed: {str(fallback_error)}")
    
    # Calculate totals including consistency and test results
    total_critical = sum(r.critical_count for r in results)
    total_medium = sum(r.medium_count for r in results)
    total_low = sum(r.low_count for r in results)
    
    if consistency_result:
        total_critical += len([i for i in consistency_result.issues if i.severity == Severity.CRITICAL])
        total_medium += len([i for i in consistency_result.issues if i.severity == Severity.MEDIUM])
        total_low += len([i for i in consistency_result.issues if i.severity == Severity.LOW])
    
    if test_results:
        for test_result in test_results:
            total_critical += len([i for i in test_result.issues if i.severity == Severity.CRITICAL])
            total_medium += len([i for i in test_result.issues if i.severity == Severity.MEDIUM])
            total_low += len([i for i in test_result.issues if i.severity == Severity.LOW])
    
    # API type summary
    type_counts = {}
    for result in results:
        api_type = result.api_type.value
        type_counts[api_type] = type_counts.get(api_type, 0) + 1
    
    print(f"\n🎯 **Review Complete** (Commonalities {commonalities_version})")
    if repo_name:
        print(f"Repository: {repo_name}")
    if issue_number:
        print(f"PR: #{issue_number}")
    print(f"Individual APIs: {len(results)}")
    for api_type, count in type_counts.items():
        print(f"  - {api_type}: {count}")
    print(f"Multi-file Consistency: {'✅ Checked' if consistency_result else '⏭️ Skipped (single file)'}")
    print(f"Test Alignment: {'✅ Checked' if test_results else '⏭️ Skipped (no tests found)'}")
    print(f"Total Critical Issues: {total_critical}")
    print(f"Total Medium Issues: {total_medium}")
    print(f"Total Low Issues: {total_low}")
    
    # Exit with appropriate code based on critical issues found
    if total_critical > 0:
        print(f"\n⚠️ Exiting with code 1 due to {total_critical} critical issue(s) found")
        sys.exit(1)  # Critical issues found - workflow will show "X critical issue(s) found"
    else:
        print("\n✅ Exiting with code 0 - no critical issues found")
        sys.exit(0)  # No critical issues - workflow will show "No critical issues found"

if __name__ == "__main__":
    main()