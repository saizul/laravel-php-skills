<?php

namespace App\Services;

class Feature
{
    public function on(): bool
    {
        return (bool) env('FEATURE_X', false);
    }
}
