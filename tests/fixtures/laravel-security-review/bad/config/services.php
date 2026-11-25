<?php

use Illuminate\Support\Facades\Http;

return [
    'client' => fn () => Http::withoutVerifying()->baseUrl('https://api.example.com'),
];
