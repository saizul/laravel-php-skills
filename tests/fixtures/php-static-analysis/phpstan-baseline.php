<?php declare(strict_types = 1);

$ignoreErrors = [];
$ignoreErrors[] = [
	'message' => '#^Access to an undefined property App\\\\Models\\\\User\\:\\:\\$profile\\.$#',
	'identifier' => 'property.notFound',
	'count' => 12,
	'path' => __DIR__ . '/app/Http/Controllers/ProfileController.php',
];
$ignoreErrors[] = [
	'message' => '#^Method App\\\\Models\\\\User\\:\\:posts\\(\\) has no return type specified\\.$#',
	'identifier' => 'missingType.return',
	'count' => 2,
	'path' => __DIR__ . '/app/Models/User.php',
];

return ['parameters' => ['ignoreErrors' => $ignoreErrors]];
