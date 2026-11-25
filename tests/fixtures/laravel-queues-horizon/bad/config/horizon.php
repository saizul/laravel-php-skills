<?php

return [
    'use' => 'default',
    'prefix' => env('HORIZON_PREFIX', 'laravel_horizon:'),
    'waits' => ['redis:default' => 60],
    'defaults' => [
        'supervisor-1' => [
            'connection' => 'redis',
            'queue' => ['default'],
            'balance' => 'auto',
            'maxProcesses' => 1,
            'memory' => 128,
            'tries' => 0,
            'timeout' => 90,
        ],
    ],
    'environments' => [
        'production' => [
            'supervisor-1' => [
                'maxProcesses' => 10,
            ],
        ],
    ],
];
