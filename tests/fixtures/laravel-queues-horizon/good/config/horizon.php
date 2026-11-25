<?php

return [
    'trim' => ['recent' => 60, 'pending' => 60, 'completed' => 60, 'failed' => 10080, 'monitored' => 10080],
    'defaults' => [
        'supervisor-1' => [
            'connection' => 'redis',
            'queue' => ['default'],
            'maxProcesses' => 4,
            'tries' => 3,
            'timeout' => 60,
        ],
    ],
];
